#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from os.path import join, isdir
import subprocess
import pathlib
import numpy as np
from imageio import imwrite as imsave
import shutil

from . import util
from . import choice_formatter
try:
    from . import hg_launcher
except ImportError as e:
    util.warn("[WARNING] CANNOT IMPORT hg_launcher. This node is incapable of training/prediction")
    # Note: do NOT raise exceptions in modules loaded by __init__.py

def _deploy(ws):
    ws.deploy_to_gpu(util.WORKSPACE_SIGNATURE_FILE,
                     util.WORKSPACE_CONFIG_FILE,
                     util.TRAINING_DIR+'/',
                     util.TESTING_DIR+'/')
    if isdir(ws.local_ws(util.EXTRA_TRAINING_DIR)):
        ws.deploy_to_gpu(util.EXTRA_TRAINING_DIR + '/')

def _fetch(ws):
    ws.fetch_gpu(util.TESTING_DIR+'/')

def write_pidfile(pidfile, pid):
    with open(pidfile, 'w') as f:
        print(pid, file=f)

def _train(ws, geo_type):
    params = hg_launcher.create_default_config()
    params['ompl_config'] = ws.training_puzzle
    if isdir(ws.local_ws(util.EXTRA_TRAINING_DIR)):
        all_omplcfgs = []
        for puzzle_fn, puzzle_name in ws.training_puzzle_generator():
            all_omplcfgs.append(puzzle_fn)
        params['all_ompl_configs'] = all_omplcfgs
    params['what_to_render'] = geo_type
    params['checkpoint_dir'] = ws.local_ws(util.NEURAL_SCRATCH, geo_type) + '/'
    params['suppress_hot'] = 0.0
    params['suppress_cold'] = 0.7
    os.makedirs(ws.local_ws(util.NEURAL_SCRATCH), exist_ok=True)
    pidfile = ws.local_ws(util.NEURAL_SCRATCH, geo_type + '.pid')
    write_pidfile(pidfile, os.getpid())
    hg_launcher.launch_with_params(params, do_training=True)
    write_pidfile(pidfile, -1)

def train_rob(args, ws):
    if args.only_wait:
        print("Note: --only_wait has no effect in train_rob")
    _train(ws, 'rob')

def train_env(args, ws):
    if args.only_wait:
        print("Note: --only_wait has no effect in train_env")
    _train(ws, 'env')

def wait_for_training(args, ws):
    for geo_type in ['rob', 'env']:
        pidfile = ws.local_ws(util.NEURAL_SCRATCH, geo_type + '.pid')
        pid = -1
        with open(pidfile, 'r') as f:
            for line in f:
                for s in line.split(' '):
                    pid = int(s)
                    break
        ret = 1
        util.log('[wait_for_training] waiting pid {} for file {}'.format(pid, pidfile))
        while ret != 0:
            ret = util.pwait(pid)
        util.log("[wait_for_training] {} (pid: {}) waited".format(geo_type, pid))
        write_pidfile(pidfile, -1)

def _predict_surface(args, ws, geo_type):
    for puzzle_fn, puzzle_name in ws.test_puzzle_generator():
        params = hg_launcher.create_default_config()
        params['ompl_config'] = puzzle_fn
        params['what_to_render'] = geo_type
        params['checkpoint_dir'] = ws.local_ws(util.NEURAL_SCRATCH, geo_type) + '/'
        params['dataset_name'] = puzzle_name # Enforce the generated filename
        util.log("[prediction] Predicting {}:{}".format(puzzle_fn, geo_type))
        hg_launcher.launch_with_params(params, do_training=False)
        src = ws.local_ws(util.NEURAL_SCRATCH, geo_type, '{}-atex.npz'.format(puzzle_name))
        dst = ws.local_ws(util.TESTING_DIR, puzzle_name, '{}-atex.npz'.format(geo_type))
        util.log("[prediction] Copy surface prediction file {} => {}".format(src, dst))
        shutil.copy(src, dst)

def predict_rob(args, ws):
    _predict_surface(args, ws, 'rob')

def predict_env(args, ws):
    _predict_surface(args, ws, 'env')

function_dict = {
        'train_rob' : train_rob,
        'train_env' : train_env,
        'wait_for_training' : wait_for_training,
        'predict_rob' : predict_rob,
        'predict_env' : predict_env,
}

def setup_parser(subparsers):
    p = subparsers.add_parser('train',
                              help='Training/Prediction',
                              formatter_class=choice_formatter.Formatter)
    p.add_argument('--stage',
                   choices=list(function_dict.keys()),
                   help='R|Possible stages:\n'+'\n'.join(list(function_dict.keys())),
                   default='',
                   metavar='')
    p.add_argument('--only_wait', action='store_true')
    p.add_argument('dir', help='Workspace directory')

# As always, run() serves as a separator between local function and remote proxy functions
def run(args):
    if args.stage in function_dict:
        ws = util.Workspace(args.dir)
        function_dict[args.stage](args, ws)
    else:
        print("Unknown train pipeline stage {}".format(args.stage))

def _remote_command(ws, cmd, auto_retry, in_tmux):
    ws.remote_command(ws.gpu_host,
                      ws.gpu_exec(),
                      ws.gpu_ws(),
                      'train',
                      cmd,
                      auto_retry=auto_retry,
                      in_tmux=in_tmux)

def remote_train_rob(ws):
    _remote_command(ws, 'train_rob', auto_retry=True, in_tmux=True)

def remote_train_env(ws):
    _remote_command(ws, 'train_env', auto_retry=True, in_tmux=True)

def remote_wait_for_training(ws):
    _remote_command(ws, 'wait_for_training', auto_retry=True, in_tmux=False)

def remote_predict_rob(ws):
    _remote_command(ws, 'predict_rob', auto_retry=True, in_tmux=False)

def remote_predict_env(ws):
    _remote_command(ws, 'predict_env', auto_retry=True, in_tmux=False)

def autorun(args):
    ws = util.Workspace(args.dir)
    _deploy(ws)
    remote_train(ws)
    remote_wait_for_training(ws)
    remote_predict_surface(ws)
    _fetch(ws)

def collect_stages():
    return [ ('deploy_to_gpu', _deploy),
             ('train_rob', remote_train_rob),
             ('train_env', remote_train_env),
             ('wait_for_training', remote_wait_for_training),
             ('predict_rob', remote_predict_rob),
             ('predict_env', remote_predict_env),
             ('fetch_from_gpu', _fetch),
           ]
