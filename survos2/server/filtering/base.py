import math
import numbers
import numpy as np

from skimage.filters import gaussian
from skimage import img_as_float
from scipy import ndimage

from skimage import exposure


import torch
from torch import nn
from torch.nn import functional as F
import kornia
from loguru import logger


def simple_invert(data, sigma=5.0):
    return 1.0 - data


def median_filter(data, size=5):
    return ndimage.median_filter(data, size=size)


def gamma_correct(data, gamma=1):
    return exposure.adjust_gamma(data, gamma)
