'''
    datan.py

    DATa ANalysis
'''

import numpy as np
import argparse

# try:
#    from os import scandir, walk
#except ImportError:
import os
from scandir import scandir, walk

def output(args):
    pack = np.load(args.infile)
    binary_misp = pack['BMISP']
    misp_advantage = pack['MISPA']
    print(np.transpose(binary_misp))
    print(np.transpose(np.sum(binary_misp,axis=0)))
    print('total {}:'.format(np.sum(binary_misp)))
    np.set_printoptions(floatmode='fixed', suppress=True, linewidth=200, precision=3)
    print(np.transpose(misp_advantage/np.clip(binary_misp,1,None)))

def analysis(args):
    # binary_misp[P,A] means mis-prediction A as P
    binary_misp = np.zeros((args.nactions, args.nactions), dtype=int)
    misp_advantage = np.zeros((args.nactions, args.nactions), dtype=np.float64)
    for ent in scandir(path=args.dir):
        if not ent.name.startswith('Pred') or not ent.is_file():
            continue
        fn = os.path.join(args.dir, ent.name)
        d = np.load(fn)
        P = d['P'][0]
        A = d['A']
        # print(P)
        # print(np.argmax(P))
        # print(A)
        mp = np.argmax(P)
        binary_misp[mp, A] += 1
        misp_advantage[mp, A] += P[mp] - P[A]
    print(binary_misp)
    print(misp_advantage/binary_misp)
    np.savez(args.out, BMISP=binary_misp, MISPA=misp_advantage)

def main():
    parser = argparse.ArgumentParser(description='Data analysis of mispredictions.')
    parser.add_argument('--infile', metavar='FILE', help='Misprediction files to read', default='')
    parser.add_argument('--out', metavar='FILE', help='.npz file that stores to statistical data', default='')
    parser.add_argument('--dir', metavar='DIR', help='Directory that stores misprediction files', default='')
    parser.add_argument('--nactions', metavar='NUMBER', help='Total number of actions', type=int, default=12)
    args = parser.parse_args()
    if args.infile:
        output(args)
        return
    if not args.out or not args.dir:
        print('Insufficient arguments. --out and --dir is required for collecting data, --in is require to show the data')
        return
    analysis(args)

if __name__ == '__main__':
    main()