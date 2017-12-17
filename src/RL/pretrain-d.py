'''
    pretrain.py

    Pre-Train the VisionNet and Inverse Model
'''

import tensorflow as tf
import numpy as np
import math
import aniconf12 as aniconf
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import sys
import os
import time
import util
import argparse
import uw_random
import config
import vision
import pyosr
import icm
import threading
import Queue as queue # Python 2, rename to import queue as queue for python 3

MT_VERBOSE = False
# MT_VERBOSE = True
VIEW_CFG = config.VIEW_CFG

def setup_global_variable(args):
    if args.ferev != 1:
        global VIEW_CFG
        VIEW_CFG = config.VIEW_CFG_REV2

def create_renderer():
    view_array = vision.create_view_array_from_config(VIEW_CFG)
    view_num = len(view_array)
    w = h = config.DEFAULT_RES

    dpy = pyosr.create_display()
    glctx = pyosr.create_gl_context(dpy)
    r = pyosr.Renderer()
    r.pbufferWidth = w
    r.pbufferHeight = h
    r.setup()
    r.loadModelFromFile(aniconf.env_fn)
    r.loadRobotFromFile(aniconf.rob_fn)
    r.scaleToUnit()
    r.angleModel(0.0, 0.0)
    r.default_depth = 0.0
    r.views = np.array(view_array, dtype=np.float32)
    return r

class Animator(object):
    im = None
    keys = None
    failed = False

    def __init__(self, renderer, batch, syncQ=None):
        self.renderer = renderer
        self.keys = []
        self.index = 0
        self.batch = batch
        self.failed = False
        self.syncQ = syncQ

    def buffer_rgb(self):
        index = self.index
        if self.index < len(self.keys):
            return
        if self.syncQ is None:
            self.keys, _ = uw_random.random_path(self.renderer, 0.0125 * 2, self.batch)
        else:
            self.gt = self.syncQ.get()
            self.keys = self.gt.keys
            self.syncQ.task_done()
        self.index = 0

    def get_rgb(self):
        index = self.index
        if index >= len(self.keys):
            self.buffer_rgb()
        if self.syncQ is None:
            return self.render_rgb()
        return self.read_rgb()

    def render_rgb(self):
        index = self.index
        r = self.renderer
        r.state = self.keys[index]
        r.render_mvrgbd()
        # print(r.mvrgb.shape)
        rgb = r.mvrgb.reshape((len(r.views), r.pbufferWidth, r.pbufferHeight, 3))

        print(r.state)
        valid = r.is_valid_state(r.state)
        if not valid:
            print('\tNOT COLLISION FREE, SAN CHECK FAILED')
            self.failed = True
        return rgb

    def read_rgb(self):
        return self.gt.rgb[self.index]

    def perform(self, framedata):
        if self.failed:
            return
        rgb = self.get_rgb()
        rgb = rgb[0] # First View
        if self.im is None:
            print('rgb {}'.format(rgb.shape))
            self.im = plt.imshow(rgb)
        else:
            self.im.set_array(rgb)

        self.index += 1

class GroundTruth:
    pass

def collector(syncQ, sample_num, batch_size, tid, amag, vmag):
    r = create_renderer()
    print(r)
    rgb_shape = (len(r.views), r.pbufferWidth, r.pbufferHeight, 3)
    dep_shape = (len(r.views), r.pbufferWidth, r.pbufferHeight, 1)
    if tid == 0:
        last_time = time.time()
    for i in range(sample_num):
        rgbq = []
        depq = []
        if MT_VERBOSE:
            print("!Generating Path #{} by thread {}".format(i, tid))
        keys, actions = uw_random.random_discrete_path(r, amag, vmag, batch_size)
        if MT_VERBOSE:
            print("!Path #{} generated by thread {}".format(i, tid))
        for index in range(len(keys)):
            r.state = keys[index]
            r.render_mvrgbd()
            rgb = r.mvrgb.reshape(rgb_shape)
            dep = r.mvdepth.reshape(dep_shape)
            # rgbq.append(rgb)
            # depq.append(dep)
            rgbq.append(np.copy(rgb))
            depq.append(np.copy(dep))
        if MT_VERBOSE:
            print("!Path #{} rendered by thread {}".format(i, tid))
        gt = GroundTruth()
        gt.actions = np.zeros(shape=(len(actions), 1,
            uw_random.DISCRETE_ACTION_NUMBER), dtype=np.float32)
        for i in range(len(actions)):
            gt.actions[i, 0, actions[i]] = 1.0
        gt.rgb = rgbq
        gt.dep = depq
        gt.keys = keys
        if MT_VERBOSE:
            print("!GT generated by thread {}".format(tid))
        syncQ.put(gt)
        if MT_VERBOSE:
            print("!GT by thread {} was put into Q".format(tid))
        if tid == 0 and (i+1) % 10 == 0:
            cur_time = time.time()
            print("!GT generation speed: {} samples/sec".format(10/(cur_time - last_time)))
            last_time = cur_time
    print("> GT Thread {} Exits".format(tid))

def spawn_gt_collector_thread(args):
    syncQ = queue.Queue(args.queuemax)
    threads = []
    for i in range(args.threads):
        dic = { 'syncQ' : syncQ, 'sample_num' : args.iter, 'batch_size' :
                args.batch, 'tid' : i, 'amag' : args.amag, 'vmag' : args.vmag }
        thread = threading.Thread(target=collector, kwargs=dic)
        thread.start()
        threads.append(thread)
    return threads, syncQ

def pretrain_main(args):
    '''
    CAVEAT: WE MUST CREATE RENDERER BEFORE CALLING ANY TF ROUTINE
    '''
    pyosr.init()

    if args.dryrun:
        r = create_renderer()
        fig = plt.figure()
        ra = Animator(r, args.batch)
        ani = animation.FuncAnimation(fig, ra.perform)
        plt.show()
        return
    else:
        threads, syncQ = spawn_gt_collector_thread(args)
        if args.dryrun2:
            fig = plt.figure()
            ra = Animator(None, args.batch, syncQ)
            ani = animation.FuncAnimation(fig, ra.perform)
            plt.show()
            return

    view_array = vision.create_view_array_from_config(VIEW_CFG)
    view_num = len(view_array)
    w = h = config.DEFAULT_RES

    ckpt_dir = args.ckptdir
    ckpt_prefix = args.ckptprefix
    device = args.device

    if 'gpu' in device:
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.9)
        session_config = tf.ConfigProto(gpu_options=gpu_options)
    else:
        session_config = None

    g = tf.Graph()
    util.mkdir_p(ckpt_dir)
    with g.as_default():
        global_step = tf.contrib.framework.get_or_create_global_step()
        increment_global_step = tf.assign_add(global_step, 1, name='increment_global_step')

        action = tf.placeholder(tf.float32, shape=[None, 1, uw_random.DISCRETE_ACTION_NUMBER])
        rgb_1 = tf.placeholder(tf.float32, shape=[None, view_num, w, h, 3])
        rgb_2 = tf.placeholder(tf.float32, shape=[None, view_num, w, h, 3])
        dep_1 = tf.placeholder(tf.float32, shape=[None, view_num, w, h, 1])
        dep_2 = tf.placeholder(tf.float32, shape=[None, view_num, w, h, 1])
        model = icm.IntrinsicCuriosityModule(action,
                rgb_1, dep_1,
                rgb_2, dep_2,
                config.SV_VISCFG,
                config.MV_VISCFG2,
                256,
                args.elu,
                args.ferev)
        model.get_inverse_model() # Create model.inverse_model_{params,tensor}
        all_params = model.cur_nn_params + model.next_nn_params + model.inverse_model_params
        all_params += [global_step]
        # print(all_params)
        optimizer = tf.train.AdamOptimizer(learning_rate=1e-3)
        _, predicts = model.get_inverse_model()
        loss = model.get_inverse_loss(discrete=True)
        train_op = optimizer.minimize(loss, global_step)

        tf.summary.scalar('loss', loss)
        summary_op = tf.summary.merge_all()
        train_writer = tf.summary.FileWriter(ckpt_dir + '/summary', g)

        saver = tf.train.Saver() # Save everything
        last_time = time.time()
        with tf.Session(config=session_config) as sess:
            sess.run(tf.global_variables_initializer())
            ckpt = tf.train.get_checkpoint_state(checkpoint_dir=ckpt_dir)
            print('ckpt {}'.format(ckpt))
            epoch = 0
            if ckpt and ckpt.model_checkpoint_path:
                saver.restore(sess, ckpt.model_checkpoint_path)
                accum_epoch = sess.run(global_step)
                print('Restored!, global_step {}'.format(accum_epoch))
            else:
                accum_epoch = 0
            total_epoch = args.iter * args.threads
            period_loss = 0.0
            period_correct = 0
            total_correct = 0
            while epoch < total_epoch:
                gt = syncQ.get(timeout=60)
                dic = {
                        action : gt.actions,
                        rgb_1 : gt.rgb[:-1],
                        rgb_2 : gt.rgb[1:],
                        dep_1 : gt.dep[:-1],
                        dep_2 : gt.dep[1:]
                      }
                # print("[{}] Start training".format(epoch))
                if not args.eval:
                    summary, current_loss, _ = sess.run([summary_op, loss, train_op], feed_dict=dic)
                    train_writer.add_summary(summary, accum_epoch)
                else:
                    current_loss, pred = sess.run([loss, predicts], feed_dict=dic)
                    # print(pred)
                    # print(pred.shape)
                    pred_index = np.argmax(pred, axis=2)
                    gt_index = np.argmax(gt.actions, axis=2)
                    for i in range(pred_index.shape[0]):
                        period_correct += 1 if pred_index[i, 0] == gt_index[i, 0] else 0
                        # print('pred {} gt {}'.format(pred_index[i,0], gt_index[i,0]))
                        # print('preds {} gts {}'.format(pred[i,0], gt.actions[i,0]))
                    # print('loss {}'.format(current_loss))
                # print("[{}] End training".format(epoch))
                period_loss += current_loss
                syncQ.task_done()
                if (not args.eval) and ((epoch + 1) % 1000 == 0 or time.time() - last_time >= 10 * 60 or epoch + 1 == total_epoch):
                    print("Saving checkpoint")
                    fn = saver.save(sess, ckpt_dir+ckpt_prefix, global_step=global_step)
                    print("Saved checkpoint to {}".format(fn))
                    last_time = time.time()
                if (epoch + 1) % 10 == 0:
                    print("Progress {}/{}".format(epoch, total_epoch))
                    print("Average loss during last 10 iterations: {}".format(period_loss / 10))
                    if args.eval:
                        total_correct += period_correct
                        p_correct_ratio = period_correct / (10 * pred_index.shape[0]) * 100.0
                        total_correct_ratio = total_correct / (epoch * pred_index.shape[0]) * 100.0
                        print("Average currectness during last 10 iterations: {}%. Total: {}%".format(p_correct_ratio, total_correct_ratio))
                        period_correct = 0
                    period_loss = 0
                # print("Epoch {} (Total {}) Done".format(epoch, accum_epoch))
                epoch += 1
                accum_epoch += 1
    for thread in threads:
        thread.join()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--ckptdir', help='Path for checkpoint files',
            default='ckpt/pretrain-d/')
    parser.add_argument('--ckptprefix', help='Prefix of checkpoint files',
            default='pretrain-d-ckpt')
    parser.add_argument('--device', help='Prefix of GT file names generated by aa-gt.py',
            default='/gpu:0')
    parser.add_argument('--batch', metavar='NUMBER',
            help='Batch size of each iteration in training',
            type=int, default=32)
    parser.add_argument('--queuemax', metavar='NUMBER',
            help='Capacity of the synchronized queue to store generated GT',
            type=int, default=32)
    parser.add_argument('--threads', metavar='NUMBER',
            help='Number of GT generation threads',
            type=int, default=1)
    parser.add_argument('--iter', metavar='NUMBER',
            help='Number of samples to generate by each thread',
            type=int, default=0)
    parser.add_argument('--amag', metavar='REAL NUMBER',
            help='Magnitude of discrete actions',
            type=float, default=0.0125)
    parser.add_argument('--vmag', metavar='REAL NUMBER',
            help='Magnitude of verifying action',
            type=float, default=0.0125 / 8)
    parser.add_argument('-n', '--dryrun',
            help='Visualize the generated GT without training anything',
            action='store_true')
    parser.add_argument('--dryrun2',
            help='Visualize the generated GT without training anything (MT version)',
            action='store_true')
    parser.add_argument('--elu',
            help='Use ELU instead of ReLU after each NN layer',
            action='store_true')
    parser.add_argument('--eval',
            help='Evaluate the network, rather than training',
            action='store_true')
    parser.add_argument('--ferev',
            help='Reversion of Feature Extractor',
            choices=range(1,3+1),
            type=int, default=1)

    args = parser.parse_args()
    setup_global_variable(args)
    pretrain_main(args)