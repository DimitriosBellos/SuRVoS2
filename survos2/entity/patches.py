import ast
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from pprint import pprint
from typing import Dict, List

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from loguru import logger

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset
from torch.autograd import Variable
from torch.nn import init
from torch.utils.data import DataLoader, Dataset
from torchio import IMAGE, LOCATION
from torchio.data.inference import GridAggregator, GridSampler
from torchvision import transforms
from tqdm import tqdm


from scipy import ndimage
import torchvision.utils
from skimage import data, measure
from sklearn.model_selection import train_test_split
from survos2 import survos
from survos2.entity.entities import (
    make_bounding_vols,
    make_entity_bvol,
    make_entity_df,
    calc_bounding_vols,
)


from survos2.entity.utils import get_largest_cc, get_surface, pad_vol
from survos2.entity.sampler import (
    centroid_to_bvol,
    crop_vol_and_pts,
    crop_vol_and_pts_bb,
    offset_points,
    sample_bvol,
    sample_marked_patches,
    viz_bvols,
)
from survos2.frontend.nb_utils import (
    slice_plot,
    show_images,
    view_vols_labels,
    view_vols_points,
    view_volume,
    view_volumes,
)
from survos2.server.features import generate_features, prepare_prediction_features
from survos2.server.filtering import (
    gaussian_blur_kornia,
    ndimage_laplacian,
    spatial_gradient_3d,
)
from survos2.server.filtering.morph import dilate, erode, median
from survos2.server.model import SRData, SRFeatures
from survos2.server.pipeline import Patch, Pipeline
from survos2.server.pipeline_ops import (
    clean_segmentation,
    make_acwe,
    make_bb,
    make_features,
    make_masks,
    make_noop,
    make_sr,
    predict_and_agg,
    predict_sr,
    saliency_pipeline,
)
from survos2.server.state import cfg
from survos2.server.supervoxels import generate_supervoxels



# LabeledDataset
class SmallVolDataset(Dataset):
    def __init__(
        self, images, labels, class_names=None, slice_num=None, dim=3, transform=None
    ):
        self.input_images, self.target_labels = images, labels
        self.transform = transform
        self.class_names = class_names
        self.slice_num = slice_num
        self.dim = dim

    def __len__(self):
        return len(self.input_images)

    def __getitem__(self, idx):

        image = self.input_images[idx]
        label = self.target_labels[idx]

        if self.dim == 2 and self.slice_num is not None:
            image = image[self.slice_num, :]
            image = np.stack((image, image, image)).T

        if self.transform:
            image = self.transform(image.T)
            label = self.transform(label.T)
        return image, label


def get_largest_cc(I):
    img = I > 0
    label_im, nb_labels = ndimage.label(img)
    sizes = ndimage.sum(I, label_im, range(nb_labels + 1))
    max_sz = np.max(sizes)
    lab_sz = sizes[label_im]
    cc = lab_sz == max_sz
    cc = cc.astype(int)

    return cc


def pad_vol(vol, padding):
    padded_vol = np.zeros(
        (
            vol.shape[0] + padding[0] * 2,
            vol.shape[1] + padding[1] * 2,
            vol.shape[2] + padding[2] * 2,
        )
    )

    padded_vol[
        padding[0] : vol.shape[0] + padding[0],
        padding[1] : vol.shape[1] + padding[1],
        padding[2] : vol.shape[2] + padding[2],
    ] = vol

    return padded_vol

@dataclass
class PatchWorkflow:
    vols: List[np.ndarray]
    locs: np.ndarray
    entities: dict
    bg_mask: np.ndarray
    params: dict
    gold: np.ndarray


def init_entity_workflow(project_file, roi_name, plot_all=False):
    with open(project_file) as project_file:
        wparams = json.load(project_file)
    proj = wparams["proj"]

    if proj == "vf":
        original_data = h5py.File(
            os.path.join(wparams["input_dir"], wparams["vol_fname"]), "r"
        )
        ds = original_data[wparams["dataset_name"]]
        # wf1 = ds["workflow_1"]
        wf2 = ds[wparams["workflow_name"]]

        ds_export = original_data.get("data_export")
        # wf1_wrangled = ds_export["workflow1_wrangled_export"]
        vol_shape_x = wf2[0].shape[0]
        vol_shape_y = wf2[0].shape[1]
        vol_shape_z = len(wf2)
        img_volume = wf2
        print(f"Loaded image volume of shape {img_volume.shape}")

    if proj == "hunt":
        # fname = wparams['vol_fname']
        fname = wparams["vol_fname"]
        original_data = h5py.File(os.path.join(wparams["datasets_dir"], fname), "r")
        img_volume = original_data["data"][:]
        wf1 = img_volume

    print(f"Loaded image volume of shape {img_volume.shape}")

    workflow_name = wparams["workflow_name"]
    input_dir = wparams["input_dir"]
    out_dir = wparams["outdir"]
    torch_models_fullpath = wparams["torch_models_fullpath"]
    project_file = wparams["project_file"]
    entity_fpath = wparams["entity_fpath"]
    # entity_fnames = wparams["entity_fnames"]
    entity_fname = wparams["entity_fname"]
    datasets_dir = wparams["datasets_dir"]
    entities_offset = wparams["entities_offset"]
    offset = wparams["entities_offset"]
    entity_meta = wparams["entity_meta"]
    main_bv = wparams["main_bv"]
    bg_mask_fname = wparams["bg_mask_fname"]
    gold_fname = wparams["gold_fname"]
    gold_fpath = wparams["gold_fpath"]

    #
    # load object data
    #
    entities_df = pd.read_csv(os.path.join(entity_fpath, entity_fname))
    entities_df.drop(
        entities_df.columns[entities_df.columns.str.contains("unnamed", case=False)],
        axis=1,
        inplace=True,
    )
    entity_pts = np.array(entities_df)
    # e_df = make_entity_df(entity_pts, flipxy=True)
    # entity_pts = np.array(e_df)
    scale_z, scale_x, scale_y = 1.0, 1.0, 1.0
    entity_pts[:, 0] = (entity_pts[:, 0] * scale_z) + offset[0]
    entity_pts[:, 1] = (entity_pts[:, 1] * scale_x) + offset[1]
    entity_pts[:, 2] = (entity_pts[:, 2] * scale_y) + offset[2]

    #
    # Crop main volume
    #
    main_bv = calc_bounding_vols(main_bv)
    bb = main_bv[roi_name]["bb"]
    print(f"Main bounding box: {bb}")
    roi_name = "_".join(map(str, bb))

    logger.debug(roi_name)

    #
    # load gold data
    #
    gold_df = pd.read_csv(os.path.join(gold_fpath, gold_fname))
    gold_df.drop(
        gold_df.columns[gold_df.columns.str.contains("unnamed", case=False)],
        axis=1,
        inplace=True,
    )
    gold_pts = np.array(gold_df)
    # gold_df = make_entity_df(gold_pts, flipxy=True)
    # gold_pts = np.array(e_df)
    scale_z, scale_x, scale_y = 1.0, 1.0, 1.0
    gold_pts[:, 0] = (gold_pts[:, 0] * scale_z) + offset[0]
    gold_pts[:, 1] = (gold_pts[:, 1] * scale_x) + offset[1]
    gold_pts[:, 2] = (gold_pts[:, 2] * scale_y) + offset[2]

    # precropped_wf2, gold_pts = crop_vol_and_pts_bb(
    #     img_volume, gold_pts, bounding_box=bb, debug_verbose=True, offset=True
    # )

    print(f"Loaded entities of shape {entities_df.shape}")
    
    #
    # Load bg mask
    #
    # with h5py.File(os.path.join(wparams["datasets_dir"],bg_mask_fname), "r") as hf:
    #    logger.debug(f"Loaded bg mask file with keys {hf.keys()}")

    # bg_mask_fullname = os.path.join(wparams["datasets_dir"], bg_mask_fname)
    # bg_mask_file = h5py.File(bg_mask_fullname, "r")
    # print(bg_mask_fullname)
    # bg_mask = bg_mask_file["mask"][:]

    precropped_wf2, precropped_pts = crop_vol_and_pts_bb(
        img_volume, entity_pts, bounding_box=bb, debug_verbose=True, offset=True
    )
    combined_clustered_pts, classwise_entities = organize_entities(
        precropped_wf2, precropped_pts, entity_meta, plot_all=plot_all
    )
    
    bg_mask = np.zeros_like(precropped_wf2)
    #bg_mask_crop = sample_bvol(bg_mask, bb)
    
    # bg_mask_crop = sample_bvol(bg_mask, bb)
    # print(
    #     f"Cropping background mask of shape {bg_mask.shape} with bounding box: {bb} to shape of {bg_mask_crop.shape}"
    # )

    #bg_mask_crop = bg_mask
    wf = PatchWorkflow(
        [precropped_wf2, precropped_wf2],
        combined_clustered_pts,
        classwise_entities,
        bg_mask,
        wparams,
        gold_pts,
    )

    if plot_all:
        plt.figure(figsize=(15, 15))
        plt.imshow(wf.vols[0][0, :], cmap="gray")
        plt.title("Input volume")
        slice_plot(wf.vols[1], wf.locs, None, (40, 200, 200))

    return wf


def organize_entities(
    img_vol, clustered_pts, entity_meta, flipxy=False, plot_all=False
):

    class_idxs = entity_meta.keys()

    classwise_entities = []

    for c in class_idxs:
        pt_idxs = clustered_pts[:, 3] == int(c)
        classwise_pts = clustered_pts[pt_idxs]
        clustered_df = make_entity_df(classwise_pts, flipxy=flipxy)
        classwise_pts = np.array(clustered_df)
        classwise_entities.append(classwise_pts)
        entity_meta[c]["entities"] = classwise_pts
        if plot_all:
            plt.figure(figsize=(9, 9))
            plt.imshow(img_vol[img_vol.shape[0] // 4, :], cmap="gray")
            plt.scatter(classwise_pts[:, 1], classwise_pts[:, 2], c="cyan")
            plt.title(
                str(entity_meta[c]["name"])
                + " Clustered Locations: "
                + str(len(classwise_pts))
            )

    combined_clustered_pts = np.concatenate(classwise_entities)

    return combined_clustered_pts, entity_meta


def load_patch_vols(train_vols):
    with h5py.File(train_vols[0], "r") as hf:
        print(hf.keys())
        img_vols = hf["data"][:]

    with h5py.File(train_vols[1], "r") as hf:
        print(hf.keys())
        label_vols = hf["data"][:]
    print(img_vols.shape, label_vols.shape)

    return img_vols, label_vols


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


def make_patches(
    wf,
    selected_locs,
    outdir,
    vol_num=0,
    proposal_vol=None,
    use_proposal_file=False,
    proposal_thresh=0.4,
    get_biggest_cc=False,
    padding=(64, 64, 64),
    num_augs=2,
    max_vols=-1,
    plot_all=False,
):
    # make bg mask

    target_cents = np.array(selected_locs)[:, 0:4]
    print(f"Making patches for {len(target_cents)} locations")
    target_cents = target_cents[:, [0, 2, 1, 3]]

    # Prepare patch dataset
    # selected_locs = wf.locs[wf.locs[:, 3] == 0]
    mask_vol_size = wf.params["entity_meta"][list(wf.params["entity_meta"].keys())[0]][
        "size"
    ]
    mask_vol_size = (26, 26, 26)  # for viz
    target_cents = np.array(selected_locs)[:, 0:4]
    target_cents = target_cents[:, [0, 2, 1, 3]]
    targs_all_1 = centroid_to_bvol(target_cents, bvol_dim=mask_vol_size, flipxy=True)
    mask_gt = viz_bvols(wf.vols[0], targs_all_1)
    if plot_all:
        slice_plot(
            mask_gt,
            selected_locs,
            wf.vols[0],
            (
                wf.vols[0].shape[0] // 2,
                wf.vols[0].shape[1] // 2,
                wf.vols[0].shape[2] // 2,
            ),
        )

    padded_vol = pad_vol(wf.vols[vol_num], padding)
    # padded_anno = pad_vol((proposal_vol > proposal_thresh) * 1.0, padding)
    padded_anno = pad_vol(proposal_vol, padding)
    if num_augs > 0:
        some_pts = np.vstack(
            [
                offset_points(selected_locs, padding, scale=32, random_offset=True)
                for i in range(num_augs)
            ]
        )
        print(f"Augmented point locations {some_pts.shape}")
    else:
        some_pts = offset_points(
            selected_locs, np.array(padding), scale=32, random_offset=False
        )

    if plot_all:
        slice_plot(
            padded_vol,
            None,
            padded_anno,
            (
                wf.vols[0].shape[0] // 2,
                wf.vols[0].shape[1] // 2,
                wf.vols[0].shape[2] // 2,
            ),
        )

    patch_size = padding
    marked_patches_anno = sample_marked_patches(
        padded_anno, some_pts, some_pts, patch_size=patch_size
    )
    marked_patches = sample_marked_patches(
        padded_vol, some_pts, some_pts, patch_size=patch_size
    )

    img_vols = marked_patches.vols
    bvols = marked_patches.vols_bbs
    labels = marked_patches.vols_locs[:, 3]
    label_vols = marked_patches_anno.vols
    label_bvols = marked_patches_anno.vols_bbs
    label_labels = marked_patches_anno.vols_locs[:, 3]
    marked_patches.vols_locs.shape

    print(
        f"Marked patches, unique label vols {np.unique(label_vols)}, img mean: {np.mean(img_vols[0])}"
    )

    if num_augs > 0:

        img_vols_flipped = []
        label_vols_flipped = []

        for i, vol in enumerate(img_vols):
            img_vols_flipped.append(np.fliplr(vol))
            img_vols_flipped.append(np.flipud(vol))
        for i, vol in enumerate(label_vols):
            label_vols_flipped.append(np.fliplr(vol))
            label_vols_flipped.append(np.flipud(vol))

        img_vols = np.vstack((img_vols, np.array(img_vols_flipped)))
        label_vols = np.vstack((label_vols, np.array(label_vols_flipped)))

    if get_biggest_cc:
        label_vols_f = []
        for i, lvol in enumerate(label_vols):
            label_vols_f.append(get_largest_cc(lvol))
        label_vols_f = np.array(label_vols_f)

    if max_vols > 0:
        img_vols = img_vols[0:max_vols]
        label_vols = label_vols[0:max_vols]

    raw_X_train, raw_X_test, raw_y_train, raw_y_test = train_test_split(
        img_vols, label_vols, test_size=0.2, random_state=42
    )

    print(
        f"raw_X_train {raw_X_train.shape}, raw_X_test {raw_X_test.shape}, raw_y_train{raw_y_train.shape}, raw_y_test{raw_y_test.shape}"
    )

    smallvol_mask_trans = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )
    train_dataset3d = SmallVolDataset(
        raw_X_train, raw_y_train, slice_num=None, dim=3, transform=smallvol_mask_trans
    )
    train_dataset3d.class_names = np.unique(raw_y_train).astype(np.uint16)

    test_dataset3d = SmallVolDataset(
        raw_X_test, raw_y_test, slice_num=None, dim=3, transform=smallvol_mask_trans
    )
    test_dataset3d.class_names = np.unique(raw_y_test).astype(np.uint16)

    train_loader3d = torch.utils.data.DataLoader(
        train_dataset3d, batch_size=1, shuffle=True, num_workers=0, drop_last=False
    )

    test_loader3d = torch.utils.data.DataLoader(
        test_dataset3d, batch_size=1, shuffle=False, num_workers=0, drop_last=False
    )

    if plot_all:
        for i in range(5):
            img, lbl = next(iter(train_loader3d))
            img = img.squeeze(0).numpy()
            lbl = lbl.squeeze(0).numpy()

            from survos2.frontend.nb_utils import show_images

            show_images(
                [img[padding[0] // 2, :], lbl[padding[0] // 2, :]], figsize=(4, 4)
            )

            print(f"Unique mask values: {np.unique(lbl)}")

    print(
        f"Augmented image vols shape {img_vols.shape}, label vols shape {label_vols.shape}"
    )
    # wf.params["selected_locs"] = selected_locs
    wf.params["outdir"] = outdir

    # save vols
    now = datetime.now()
    dt_string = now.strftime("%d%m_%H%M")
    output_dataset = True
    workflow_name = wf.params["workflow_name"]

    workflow_name = "patch_vols"

    if output_dataset:
        map_fullpath = os.path.join(
            wf.params["outdir"],
            str(wf.params["proj"])
            + "_"
            + str(workflow_name)
            + str(len(img_vols))
            + "_img_vols_"
            + str(dt_string)
            + ".h5",
        )
        wf.params["img_vols_fullpath"] = map_fullpath
        with h5py.File(map_fullpath, "w") as hf:
            hf.create_dataset("data", data=img_vols)

        print(f"Saving image vols {map_fullpath}")

        map_fullpath = os.path.join(
            wf.params["outdir"],
            str(wf.params["proj"])
            + "_"
            + str(workflow_name)
            + str(len(label_vols))
            + "_img_labels_"
            + str(dt_string)
            + ".h5",
        )
        wf.params["label_vols_fullpath"] = map_fullpath
        with h5py.File(map_fullpath, "w") as hf:
            hf.create_dataset("data", data=label_vols)
        print(f"Saving image vols {map_fullpath}")

        # save annotation mask (input image with the annotation volume regions masked)
        map_fullpath = os.path.join(
            wf.params["outdir"],
            str(wf.params["proj"])
            + "_"
            + str(workflow_name)
            + "_"
            + str(len(label_vols))
            + "_mask_gt_"
            + str(dt_string)
            + ".h5",
        )
        wf.params["mask_gt"] = map_fullpath
        with h5py.File(map_fullpath, "w") as hf:
            hf.create_dataset("data", data=mask_gt)
        print(f"Saving image vols {map_fullpath}")

    return wf.params["img_vols_fullpath"], wf.params["label_vols_fullpath"]



def prepare_dataloaders(
    img_vols, label_vols, model_type, batch_size=1, display_plots=False
):
    from sklearn.model_selection import train_test_split

    raw_X_train, raw_X_test, raw_y_train, raw_y_test = train_test_split(
        img_vols, (label_vols > 0) * 1.0, test_size=0.1, random_state=42
    )
    print(
        f"Prepared train X : {raw_X_train.shape} and train y: {raw_y_train.shape}  and test X: {raw_X_test.shape} and test y {raw_y_test.shape}"
    )

    smallvol_mask_trans = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )
    train_dataset3d = SmallVolDataset(
        raw_X_train, raw_y_train, slice_num=None, dim=3, transform=smallvol_mask_trans
    )
    train_dataset3d.class_names = np.unique(raw_y_train).astype(np.uint16)
    test_dataset3d = SmallVolDataset(
        raw_X_test, raw_y_test, slice_num=None, dim=3, transform=smallvol_mask_trans
    )
    test_dataset3d.class_names = np.unique(raw_y_test).astype(np.uint16)

    
    image_trans = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )

    mask_trans = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )


    if model_type != "unet" or model_type != "fpn3d":
        dataloaders = {
            "train": DataLoader(
                train_dataset3d, batch_size=batch_size, shuffle=True, num_workers=0
            ),
            "val": DataLoader(
                test_dataset3d, batch_size=batch_size, shuffle=False, num_workers=0
            ),
        }

    if display_plots:
        if model_type != "unet" or model_type != "fpn3d":
            for jj in range(1):
                for kk in range(0, 1, 1):
                    idx = np.random.randint(4)
                    img_batch, label = next(
                        islice(iter(dataloaders["val"]), idx, idx + 1)
                    )
                    print(img_batch.shape, label.shape)
                    show_images([img_batch[kk, 0, :].T, label[kk, 0, :]])
                    print(img_batch[kk, :].T.shape)

    print(list(dataloaders["train"])[0][0].shape)

    return dataloaders
