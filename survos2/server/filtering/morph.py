import numpy as np
from scipy import ndimage
from loguru import logger


def erode(I, num_iter, thresh=0.5):
    logger.info("+ Computing erosion")
    I = (I >= thresh) * 1.0
    struct2 = ndimage.generate_binary_structure(3, 2)

    for i in range(num_iter):
        I = ndimage.binary_erosion(I, structure=struct2).astype(I.dtype)

    return I


def dilate(I, num_iter, thresh=0.5):
    logger.info("+ Computing dilation")
    I = (I >= thresh) * 1.0
    struct2 = ndimage.generate_binary_structure(3, 2)

    for i in range(num_iter):
        I = ndimage.binary_dilation(I, structure=struct2).astype(I.dtype)

    return I


def median(I, median_size, num_iter, thresh=0.5):
    logger.info("+ Computing median")
    I = (I >= thresh) * 1.0

    for i in range(num_iter):
        I = ndimage.median_filter(I, median_size).astype(I.dtype)

    return I
