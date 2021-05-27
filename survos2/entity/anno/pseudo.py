import ast
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pprint import pprint
from typing import Dict, List

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import torch
import torch.nn as nn
import torch.nn.functional as F

# import torchvision.utils
from matplotlib import patches, patheffects
from napari import layers
from skimage import data, measure

from torch import optim
from torch.autograd import Variable
from torch.nn import init
from torch.optim import LBFGS, SGD, Adam, AdamW, lr_scheduler
from torch.optim.lr_scheduler import MultiStepLR, StepLR
from torch.utils.data import DataLoader, Dataset

from tqdm import tqdm

from survos2 import survos
from survos2.entity.anno.masks import generate_anno
from survos2.entity.entities import (
    make_bounding_vols,
    make_entity_bvol,
    make_entity_df,
)

from survos2.entity.sampler import (
    crop_vol_and_pts,
    crop_vol_and_pts_bb,
    sample_marked_patches,
    generate_random_points_in_volume,
)
from survos2.frontend.nb_utils import (
    slice_plot,
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
    make_acwe,
    clean_segmentation,
    make_bb,
    make_masks,
    make_noop,
    make_sr,
    predict_and_agg,
    saliency_pipeline,
)
from survos2.server.state import cfg
from survos2.server.supervoxels import generate_supervoxels

# Fixed
# AC
# SR
# Unet?


def generate_annotation_volume(
    wf,
    entity_meta,
    gt_proportion=1.0,
    padding=(64, 64, 64),
    generate_random_bg_entities=False,
    num_before_masking=60,
    acwe=False,
    stratified_selection=False,
    class_proportion={0: 1, 1: 1.0, 2: 1.0, 5: 1},
):
    entities = wf.locs
    # entities_sel = np.random.choice(
    #    range(len(entities)), int(gt_proportion * len(entities))
    # )
    # gt_entities = entities[entities_sel]

    if stratified_selection:
        stratified_entities = []
        for c in np.unique(entities[:, 3]):
            single_class = entities[entities[:, 3] == c]
            entities_sel = np.random.choice(
                range(len(single_class)), int(class_proportion[c] * len(single_class))
            )
            stratified_entities.append(single_class[entities_sel])
        gt_entities = np.concatenate(stratified_entities)
        print(f"Produced {len(gt_entities)} entities.")
    else:
        gt_entities = entities

    if generate_random_bg_entities:
        random_entities = generate_random_points_in_volume(
            wf.vols[0], num_before_masking
        ).astype(np.uint32)
        from survos2.entity.utils import remove_masked_entities

        print(
            f"Before masking random entities generated of shape {random_entities.shape}"
        )
        random_entities = remove_masked_entities(wf.bg_mask, random_entities)

        print(f"After masking: {random_entities.shape}")
        random_entities[:, 3] = np.array([6] * len(random_entities))
        # augmented_entities = np.vstack((gt_entities, masked_entities))
        # print(f"Produced augmented entities array of shape {augmented_entities.shape}")
    else:
        random_entities = []

    anno_masks, anno_all, gt_entities = make_anno(
        wf, gt_entities, entity_meta, gt_proportion, padding, acwe=acwe
    )

    return anno_masks, anno_all, gt_entities, random_entities


def make_anno(
    wf, entities, entity_meta, gt_proportion, padding, acwe=False, plot_all=True
):
    from survos2.entity.patches import organize_entities

    combined_clustered_pts, classwise_entities = organize_entities(
        wf.vols[0], entities, entity_meta, plot_all=plot_all
    )
    wf.params["entity_meta"] = entity_meta
    anno_masks, anno_all = make_pseudomasks(
        wf,
        classwise_entities,
        acwe=acwe,
        padding=padding,
        core_mask_radius=(12, 12, 12),
    )
    return anno_masks, anno_all, entities


def make_pseudomasks(
    wf,
    classwise_entities,
    padding=(64, 64, 64),
    core_mask_radius=(8, 8, 8),
    acwe=False,
    plot_all=False,
):

    anno_masks, padded_vol = generate_anno(
        wf.vols[0],
        classwise_entities,
        cfg,
        padding=padding,
        remove_padding=True,
        core_mask_radius=core_mask_radius,
    )

    anno_gen = np.sum([anno_masks[i]["mask"] for i in anno_masks.keys()], axis=0)
    anno_shell_gen = np.sum(
        [anno_masks[i]["shell_mask"] for i in anno_masks.keys()], axis=0
    )

    anno_all = [anno_masks[i]["mask"] for i in classwise_entities.keys()]
    anno_all.extend(anno_shell_gen)

    if plot_all:
        slice_plot(anno_all, None, wf.vols[0], (89, 200, 200))

    if acwe:
        p = Patch(
            {"Main": wf.vols[0]},
            {},
            {"Points": classwise_entities["0"]["entities"]},
            {},
        )
        p.image_layers["total_mask"] = (anno_gen > 0) * 1.0
        p = make_acwe(p, cfg["pipeline"])
        anno_masks["acwe"] = p.image_layers["acwe"]

    return anno_masks, anno_all
