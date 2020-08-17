from collections import namedtuple
import yaml
import pprint
from survos2.helpers import AttrDict
from dataclasses import dataclass
from survos2.improc.features import gaussian, tvdenoising3d, gaussian_norm
from survos2.server.filtering import simple_laplacian

##########################################################################
# Config yamls, get combined into a master app state dict AppState
# 

survos_config_yaml = """
scfg:
  proj: hunt
  preprocessing: {}
  calculate_features: true
  calculate_supervoxels: true
  load_pretrained_classifier: false
  load_annotation: false
  code_dir: D:/work
  nb_platform: windows
  random_seed_main: 6868842
  marker_size: 10
  refine_lambda: 1.0
  resample_amt: 0.5
  root_dir: D:/
  save_output_files: false
  computing:
    chunks: true
    chunk_size: 1024  # 1 Gb
  mscale: 1.0
  logging:
    level: info
  plot_all: false
  roi_crop: [0,2500, 0, 2500, 0, 2500]
  feats_idx: 0
  torch_models_fullpath:  c:/work/experiments
"""

filter_yaml = """
filter_cfg:
  slic_params:
    compactness: 20
    postprocess: false
    sp_shape:
    - 18
    - 18
    - 18
  filter1: 
    plugin: features
    command: compute
    feature: gaussian
    params: 3
    gauss_params:
        sigma: 2
  filter2: 
    plugin: features
    command: compute
    feature: gaussian
    params: 3
    gauss_params:
        sigma: 2
  filter3:
    plugin: features
    command: compute
    feature: tv
    tvdenoising3d_params:
        lamda: 3.7
  filter4:
    laplacian_params:
        sigma: 2.1
  filter5:
    gradient_params:
        sigma: 3
"""

loading_yaml = """
loading_cfg:
  code_dir: D:/work
  datasets_dir: D:/datasets/
  experiments_dir: D:/work
  root_dir: D:/
  sdata_rootpath: D:/datasets/VF_S1/
"""
#output: D:/datasets/well_hunt/output


predict_yaml = """
predict_cfg:
  predict_params:
    n_estimators: 10
    proj: False
"""


@dataclass
class AppState:
    scfg:AttrDict
#    params : Parameter    

scfg = AttrDict(yaml.safe_load(survos_config_yaml)['scfg'])
filter_cfg = AttrDict(yaml.safe_load(filter_yaml)['filter_cfg'])
loading_cfg = AttrDict(yaml.safe_load(loading_yaml)['loading_cfg'])
predict_cfg = AttrDict(yaml.safe_load(predict_yaml)['predict_cfg'])


# merge config dictionaries to make app state 
scfg = {**scfg, **filter_cfg}
scfg = {**scfg, **loading_cfg}
scfg = {**scfg, **predict_cfg}

scfg = AttrDict(scfg)

appState= AppState(scfg)
#appState = AppState(scfg, params)

scfg.widget = None
scfg.p = None


scfg.feature_params = {}
scfg.feature_params['simple_gaussian'] = [ 
  [gaussian, scfg.filter2['gauss_params'] ]]
scfg.feature_params['vf'] = [ [gaussian, scfg.filter1['gauss_params']],
      [gaussian, scfg.filter2['gauss_params'] ],
      [simple_laplacian, scfg.filter4['laplacian_params'] ],
      [tvdenoising3d, scfg.filter3['tvdenoising3d_params'] ]]
scfg.feature_params['vf2'] = [
  [gaussian, scfg.filter2['gauss_params'] ]]
#      [simple_laplacian, scfg.filter4['laplacian_params'] ],
#      [tvdenoising3d, scfg.filter3['tvdenoising3d_params'] ]]
