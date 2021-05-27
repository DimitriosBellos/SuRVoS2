import math
import os
import random
import sys
from math import sqrt
from typing import List, Optional


import matplotlib.pyplot as plt
import numpy as np
import skimage
import torch
from matplotlib import patches
from matplotlib.patches import Rectangle
from skimage import data, img_as_float, img_as_ubyte
from skimage.color import label2rgb, rgb2gray
from skimage.feature import blob_dog, blob_doh, blob_log
from skimage.measure import find_contours, label, regionprops
from skimage.morphology import dilation, disk, erosion
from sklearn.model_selection import StratifiedKFold, train_test_split
from survos2.entity.sampler import sample_bvol
from survos2.frontend.nb_utils import summary_stats
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, models, transforms


def sample_bounding_volume(img_volume, bvol, patch_size):
    z_st, x_st, y_st, z_end, x_end, y_end = bvol
    # print(img_volume.shape, z_st, x_st, y_st, z_end, x_end, y_end)
    if (
        z_st > 0
        and z_end < img_volume.shape[0]
        and x_st > 0
        and x_end < img_volume.shape[1]
        and y_st > 0
        and y_end < img_volume.shape[2]
    ):

        img = img_volume[z_st:z_end, y_st:y_end, x_st:x_end]
    else:
        img = np.zeros(patch_size)

    return img


class FilteredVolumeDataset(Dataset):
    def __init__(
        self,
        images: List[np.ndarray],
        bvols: List[np.ndarray],
        labels: List[List[int]],
        patch_size=(32, 32, 32),
        transform=None,
        plot_verbose=False,
    ):
        self.images, self.bvols, self.labels = images, bvols, labels
        self.transform = transform
        self.plot_verbose = plot_verbose
        self.patch_size = np.array(patch_size)
        print(f"Setting FilteredVolumeDataset patch size to {self.patch_size}")

    def __len__(self):
        return len(self.bvols)

    def __getitem__(self, idx):
        bvol = self.bvols[idx]
        label = self.labels[idx]
        samples = []

        for filtered_vol in self.images:
            # print(self.patch_size)
            sample = sample_bounding_volume(
                filtered_vol, bvol, patch_size=self.patch_size
            )
            samples.append(sample)

        if self.transform:
            sample = self.transform(sample)

        box_volume = sample.shape[0] * sample.shape[1] * sample.shape[2]

        target = {}
        target["boxes"] = bvol
        target["labels"] = label
        target["image_id"] = idx
        target["box_volume"] = box_volume

        return samples, target


class BoundingVolumeDataset(Dataset):
    def __init__(
        self,
        image: np.ndarray,
        bvols: List[np.ndarray],
        labels=List[List[int]],
        patch_size=(64, 64, 64),
        transform=None,
        plot_verbose=False,
    ):
        self.image, self.bvols, self.labels = image, bvols, labels
        self.transform = transform
        self.plot_verbose = plot_verbose
        self.patch_size = patch_size

    def __len__(self):
        return len(self.bvols)

    def __getitem__(self, idx):
        bvol = self.bvols[idx]
        label = self.labels[idx]
        image = sample_bounding_volume(self.image, bvol, patch_size=self.patch_size)

        if self.transform:
            image = self.transform(image)

        box_volume = image.shape[0] * image.shape[1] * image.shape[2]
        target = {}

        target["boxes"] = bvol
        target["labels"] = label
        target["image_id"] = idx
        target["box_volume"] = box_volume

        return image, target


class LabeledVolDataset(Dataset):
    def __init__(self, image, labels, transform=None, threechan=True):

        self.image, self.labels = image, labels
        self.transform = transform
        self.threechan = threechan

    def __len__(self):
        return self.image.shape[0]

    def __getitem__(self, idx):

        image = self.image[idx, :]
        label = self.labels[idx, :]
        # label = np.stack((self.labels[0][idx,:],self.labels[1][idx,:],self.labels[2][idx,:])).T
        from skimage import transform

        if self.threechan:
            image = np.stack((image, image, image)).T
        if self.transform:
            image = self.transform(image)
            label = self.transform(label)

        image = image.float()
        label = label.float()

        return [image, label]


class SimpleDetDataset(Dataset):
    def __init__(self, images, labels, transform=None):
        self.images = images
        self.labels = labels
        self.transform = transform

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        image = self.images[idx]
        label = self.labels[idx]
        if self.transform:
            image = self.transform(image).unsqueeze(0).unsqueeze(0)
        batch = {}
        batch["data"] = image
        batch.update(label)

        return batch


class SimpleVolumeDataset(Dataset):
    def __init__(self, images, labels, transform=None):
        self.images = images
        self.labels = labels
        self.transform = transform

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        image = self.images[idx]
        label = self.labels[idx]

        if self.transform:
            image = self.transform(image)

        return [image, label]


class MaskedDataset(Dataset):
    def __init__(self, images, masks, transform=None):

        self.input_images, self.target_masks = images, masks
        self.transform = transform

    def __len__(self):
        return len(self.input_images)

    def __getitem__(self, idx):

        image = self.input_images[idx]
        mask = self.target_masks[idx]

        if self.transform:
            image = self.transform(image)

        return [image, mask]


def setup_dataloaders_masked():
    train_set = MaskedDataset(images_train, masks_train, transform=image_trans)
    val_set = MaskedDataset(images_val, masks_train, transform=image_trans)

    image_datasets = {"train": train_set, "val": val_set}

    batch_size = 32

    dataloaders = {
        "train": DataLoader(
            train_set, batch_size=batch_size, shuffle=False, num_workers=0
        ),
        "val": DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=0),
    }

    return dataloaders



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

        if self.dim == 2:
            if self.slice_num is not None:
                image = image[self.slice_num, :]
                image = np.stack((image, image, image)).T

        if self.transform:
            image = self.transform(image.T)
            label = self.transform(label.T)
        return image, label


def setup_dataloaders_smallvol():

    smallvol_image_trans = transforms.Compose(
        [
            transforms.ToTensor(),
            # transforms.Normalize([0.450, 0.450, 0.450], [0.225, 0.225, 0.225]) # imagenet
        ]
    )

    smallvol_mask_trans = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )

    train_set = SmallVolDataset(slice_shortlist, labs, transform=image_trans)
    val_set = MaskedDataset(slice_val, masks_train, transform=image_trans)
    image_datasets = {"train": train_set, "val": val_set}

    dataloaders = {
        "train": DataLoader(
            train_set, batch_size=batch_size, shuffle=False, num_workers=0
        ),
        "val": DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=0),
    }

    return dataloaders

