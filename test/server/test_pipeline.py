import os
import pytest
import h5py
import numpy as np 

from survos2 import survos
from survos2.improc.utils import DatasetManager
import survos2.frontend.control
from survos2.frontend.control import Launcher
from survos2.frontend.control import DataModel

#from loguru import logger

from torch.testing import assert_allclose


def test_mask_pipeline(p: Patch):
    p = make_masks(p)
    p.image_layers['result'] = p.image_layers['total_mask']
    
    return p

def test_survos_pipeline(self, p: Patch):
    p = predict_sr(s)    
    
    return p

def test_superregion_pipeline(self, p: Patch):
    p = make_masks(s)
    p = make_features(s)
    p = make_sr(s)

    p.image_layers['result'] = s.superregions.supervoxel_vol
    
    return p

def test_prediction_pipeline(self, p: Patch):
    p = make_masks(s)
    p = make_features(s )
    p = make_sr(s)
    # p = do_acwe(p)
    p = predict_sr(s)
    
    p.image_layers['result'] = p.image_layers['prediction']
    
    return p