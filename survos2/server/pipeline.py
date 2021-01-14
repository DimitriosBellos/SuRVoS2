"""
Pipeline ops

"""
import os
import numpy as np
from typing import List, Optional, Dict
import itertools

from dataclasses import dataclass

from tqdm import tqdm

from loguru import logger

from survos2.server.model import SRFeatures


@dataclass
class Patch:
    """A Patch is processed by a Pipeline

    3 layer dictionaries for the different types (float image, integer image, geometry)

    Pipeline functions need to agree on the names they
    use for layers.

    TODO Adapter
    """

    image_layers: Dict
    annotation_layers: Dict
    geometry_layers: Dict
    features: SRFeatures


class Pipeline:
    """
    A pipeline produces output such as a segmentation, and often has
    several different inputs of several different types as well as a
    dictionary of parameters (e.g. a superregion segmentation takes
    an annotation uint16, a supervoxel uint32 and multiple float32 images)

    A pipeline follows the iterator protocol. The caller creates an instance,
    providing the list of operations and a payload and then iterates through
    the pipeline. The payload may be changed with init_payload. The result Patch
    is obtained by calling output_result


    """

    def __init__(self, params, models=None):
        self.params = params
        self.ordered_ops = iter(params["ordered_ops"])
        self.payload = None

    def init_payload(self, patch):
        self.payload = patch

    def output_result(self):
        return self.payload

    def __iter__(self):
        return self

    def __next__(self):
        self.payload = next(self.ordered_ops)(self.payload)
        return self.payload
