import os
import json
import h5py
import z5py
import numpy as np

import luigi
from cluster_tools.morphology import MorphologyWorkflow
from cluster_tools.morphology import RegionCentersWorkflow
from .util import write_csv


def make_config(tmp_folder):
    configs = MorphologyWorkflow.get_config()
    config_folder = os.path.join(tmp_folder, 'configs')
    os.makedirs(config_folder, exist_ok=True)
    global_config = configs['global']
    # TODO use new platy browser env
    shebang = '#! /g/kreshuk/pape/Work/software/conda/miniconda3/envs/cluster_env37/bin/python'
    global_config['shebang'] = shebang
    global_config['block_shape'] = [64, 512, 512]
    with open(os.path.join(config_folder, 'global.config'), 'w') as f:
        json.dump(global_config, f)


def n5_attributes(input_path, input_key, tmp_folder, target, max_jobs):
    task = MorphologyWorkflow

    out_path = os.path.join(tmp_folder, 'data.n5')
    config_folder = os.path.join(tmp_folder, 'configs')

    out_key = 'attributes'
    t = task(tmp_folder=tmp_folder, max_jobs=max_jobs, target=target,
             config_dir=config_folder,
             input_path=input_path, input_key=input_key,
             output_path=out_path, output_key=out_key,
             prefix='attributes', max_jobs_merge=min(32, max_jobs))
    ret = luigi.build([t], local_scheduler=True)
    if not ret:
        raise RuntimeError("Attribute workflow failed")
    return out_path, out_key


# set the anchor to region center (= maximum of boundary distance transform
# inside the object) instead of com
def run_correction(input_path, input_key,
                   tmp_folder, target, max_jobs):
    task = RegionCentersWorkflow
    config_folder = os.path.join(tmp_folder, 'configs')

    out_path = os.path.join(tmp_folder, 'data.n5')
    out_key = 'region_centers'

    # we need to run this at a lower scale, as a heuristic,
    # we take the first scale with all dimensions < 1750 pix
    # (corresponds to scale 4 in sbem)
    max_dim_size = 1750
    scale_key = input_key
    with h5py.File(input_path, 'r') as f:
        while True:
            shape = f[scale_key].shape
            if all(sh <= max_dim_size for sh in shape):
                break

            scale = int(scale_key.split('/')[2]) + 1
            next_scale_key = 't00000/s00/%i/cells' % scale
            if next_scale_key not in f:
                break
            scale_key = next_scale_key

    with h5py.File(input_path, 'r') as f:
        shape1 = f[input_key].shape
        shape2 = f[scale_key].shape
    scale_factor = np.array([float(sh1) / sh2 for sh1, sh2 in zip(shape1, shape2)])

    t = task(tmp_folder=tmp_folder, config_dir=config_folder,
             max_jobs=max_jobs, target=target,
             input_path=input_path, input_key=scale_key,
             output_path=out_path, output_key=out_key,
             ignore_label=0)
    ret = luigi.build([t], local_scheduler=True)
    if not ret:
        raise RuntimeError("Anchor correction failed")

    with z5py.File(out_path, 'r') as f:
        anchors = f[out_key][:]
    anchors *= scale_factor
    return anchors


def to_csv(input_path, input_key, output_path, resolution,
           anchors=None):
    # load the attributes from n5
    with z5py.File(input_path, 'r') as f:
        attributes = f[input_key][:]
    label_ids = attributes[:, 0:1]

    # the colomn names
    col_names = ['label_id',
                 'anchor_x', 'anchor_y', 'anchor_z',
                 'bb_min_x', 'bb_min_y', 'bb_min_z',
                 'bb_max_x', 'bb_max_y', 'bb_max_z',
                 'n_pixels']

    # we need to switch from our axis conventions (zyx)
    # to java conventions (xyz)
    res_in_micron = resolution[::-1]
    # reshuffle the attributes to fit the output colomns

    def translate_coordinate_tuple(coords):
        coords = coords[:, ::-1]
        for d in range(3):
            coords[:, d] *= res_in_micron[d]
        return coords

    # center of mass / anchor points
    com = attributes[:, 2:5]
    if anchors is None:
        anchors = translate_coordinate_tuple(com)
    else:
        assert len(anchors) == len(com)
        assert anchors.shape[1] == 3

        # some of the corrected anchors might not be present,
        # so we merge them with the com here
        invalid_anchors = np.isclose(anchors, 0.).all(axis=1)
        anchors[invalid_anchors] = com[invalid_anchors]
        anchors = translate_coordinate_tuple(anchors)

    # attributes[5:8] = min coordinate of bounding box
    minc = translate_coordinate_tuple(attributes[:, 5:8])
    # attributes[8:11] = min coordinate of bounding box
    maxc = translate_coordinate_tuple(attributes[:, 8:11])

    # NOTE: attributes[1] = size in pixel
    # make the output attributes
    data = np.concatenate([label_ids, anchors, minc, maxc, attributes[:, 1:2]], axis=1)
    write_csv(output_path, data, col_names)


def base_attributes(input_path, input_key, output_path, resolution,
                    tmp_folder, target, max_jobs, correct_anchors=True):

    # prepare cluster tools tasks
    make_config(tmp_folder)

    # make base attributes as n5 dataset
    tmp_path, tmp_key = n5_attributes(input_path, input_key,
                                      tmp_folder, target, max_jobs)

    # correct anchor positions
    if correct_anchors:
        anchors = run_correction(input_path, input_key,
                                 tmp_folder, target, max_jobs)
    else:
        anchors = None

    # write output to csv
    to_csv(tmp_path, tmp_key, output_path, resolution, anchors)

    # load and return label_ids
    with z5py.File(tmp_path, 'r') as f:
        label_ids = f[tmp_key][:, 0]
    return label_ids