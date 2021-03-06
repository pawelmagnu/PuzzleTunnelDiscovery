# SPDX-FileCopyrightText: Copyright © 2020 The University of Texas at Austin
# SPDX-FileContributor: Xinya Zhang <xinyazhang@utexas.edu>
# SPDX-License-Identifier: GPL-2.0-or-later
import tensorflow as tf
import numpy as np
import vision
import config
import warnings

class IntrinsicCuriosityModule:
    action_tensor = None
    rgb_tensor = None
    depth_tensor = None
    next_rgb_tensor = None
    next_depth_tensor = None
    feature_extractor = None
    inverse_fc_applier = None
    inverse_model_params = None
    inverse_output_tensor = None
    forward_model_params = None
    forward_output_tensor = None
    imhidden_params = None
    fwhidden_params = None

    '''
    Persumably these tensors shall be placeholders
    '''
    def __init__(self,
            action_tensor,
            rgb_tensor,
            depth_tensor,
            next_rgb_tensor,
            next_depth_tensor,
            svconfdict,
            mvconfdict,
            featnum,
            elu,
            ferev=1,
            imhidden=[],
            fehidden=[1024,1024],
            fwhidden=[],
            permuation_matrix=None,
            batch_normalization=None):
        print('! IntrinsicCuriosityModule')
        print('! ICM FEREV {}'.format(ferev))
        # assert ferev == 13, "[DEBUG slimnet-2] --ferev should be 13"
        self.action_tensor = action_tensor
        self.rgb_tensor = rgb_tensor
        self.depth_tensor = depth_tensor
        self.next_rgb_tensor = next_rgb_tensor
        self.next_depth_tensor = next_depth_tensor
        self.pretrain_saver = None
        self.pm = permuation_matrix
        self.view_num = int(rgb_tensor.shape[1])
        self.batch_normalization = batch_normalization
        '''
        pm_tensor: shape [VIEW, ACTION, ACTION]
        '''
        if self.pm is not None:
            self.pm_tensor = tf.constant(permuation_matrix)
            ipm = np.array([m.transpose() for m in permuation_matrix])
            self.ipm_tensor = tf.constant(ipm)
        if not imhidden:
            self.imhidden_params = list(config.INVERSE_MODEL_HIDDEN_LAYER)
        else:
            self.imhidden_params = list(imhidden)
        if not fwhidden:
            self.fwhidden_params =list(config.FORWARD_MODEL_HIDDEN_LAYERS)
        else:
            self.fwhidden_params =list(fwhidden)

        if ferev == 1:
            self.feature_extractor = vision.FeatureExtractor(svconfdict, mvconfdict, featnum, featnum, 'VisionNet', elu)
        elif ferev == 2:
            self.feature_extractor = vision.FeatureExtractorRev2(svconfdict,
                    128, [featnum * 2, featnum], 'VisionNetRev2', elu)
        elif ferev == 3:
            self.feature_extractor = vision.FeatureExtractorRev3(svconfdict,
                    128, [featnum * 2, featnum], 'VisionNetRev3', elu)
        elif ferev == 4:
            self.feature_extractor = vision.FeatureExtractorRev4(
                    config.SV_SHARED,
                    config.SV_NON_SHARED,
                    int(rgb_tensor.shape[1]),
                    [128, 128],
                    [featnum * 2, featnum], 'VisionNetRev4', elu)
        elif ferev == 5:
            self.feature_extractor = vision.FeatureExtractorRev5(
                    config.SV_NAIVE,
                    fehidden + [featnum], 'VisionNetRev5', elu)
        elif ferev == 6:
            self.feature_extractor = vision.FeatureExtractorRev6(
                    config.SV_HOLE_LOWRES,
                    fehidden + [featnum], 'VisionNetRev6', elu)
        elif ferev == 7:
            self.feature_extractor = vision.FeatureExtractorRev6(
                    config.SV_HOLE_MIDRES,
                    fehidden + [featnum], 'VisionNetRev7', elu)
        elif ferev == 8:
            self.feature_extractor = vision.FeatureExtractorRev6(
                    config.SV_HOLE_HIGHRES,
                    fehidden + [featnum], 'VisionNetRev8', elu)
        elif ferev == 9:
            self.feature_extractor = vision.FeatureExtractorRev5(
                    config.SV_VGG16_STRIDES,
                    fehidden + [featnum], 'VisionNetRev9', elu)
        elif ferev == 10:
            self.feature_extractor = vision.FeatureExtractorRev5(
                    config.SV_NAIVE_224,
                    fehidden + [featnum], 'VisionNetRev10', elu)
        elif ferev == 11:
            self.feature_extractor = vision.FeatureExtractorResNet(
                    config.SV_RESNET18,
                    fehidden + [featnum], 'VisionNetRev11', elu,
                    batch_normalization=batch_normalization)
        elif ferev == 12:
            self.feature_extractor = vision.FeatureExtractorResNet(
                    config.SV_RESNET18,
                    fehidden + [featnum], 'VisionNetRev12', elu, gradb=True,
                    batch_normalization=batch_normalization)
        elif ferev == 13:
            self.feature_extractor = vision.FeatureExtractorResNet(
                    config.SV_RESNET18_TRUE,
                    fehidden + [featnum], 'VisionNetRev13', elu,
                    batch_normalization=batch_normalization)
        '''
        featvec: shape [BATCH, VIEW, N]
        '''
        self.cur_nn_params, self.cur_featvec = self.feature_extractor.infer(rgb_tensor, depth_tensor)
        print('Feature shape {}'.format(self.cur_featvec.shape))
        B,V,N = self.cur_featvec.shape
        self.cur_mvfeatvec = tf.reshape(self.cur_featvec, [-1, 1, int(V)*int(N)])
        print('MV Feature shape {}'.format(self.cur_mvfeatvec.shape))
        self.next_nn_params, self.next_featvec = self.feature_extractor.infer(next_rgb_tensor, next_depth_tensor)
        self.elu = elu
        if hasattr(self.feature_extractor, 'cat_nn_vars'):
            self.cat_nn_vars = self.feature_extractor.cat_nn_vars
        else:
            warnings.warn("selected feature_extractor does not expose cat_nn_vars attribute")
            warnings.warn("Consider switching to --ferev 11 or --ferev 12")

        self.featnum = featnum
        self.lstmsize = featnum
        self.lstm_dic = {}
        self.action_space_dimension = int(self.action_tensor.shape[-1])

    def create_pretrain_saver(self, view=0):
        self.get_inverse_model()
        ''' Note: cur nn and next nn share params '''
        params = self.cur_nn_params + self.inverse_model_params
        # print('+*+ ICM load params from {}: {}'.format(ckpt_dir, params))
        self.pretrain_saver = tf.train.Saver(params)
        self.pretrain_saver.view = view

    def load_pretrain(self, sess, ckpt_dir, view=0):
        if self.pretrain_saver is None:
            self.create_pretrain_saver(view=view)
        params = self.cur_nn_params + self.inverse_model_params
        print('+*+ ICM load params from {}:'.format(ckpt_dir))
        for p in params:
            print("\t{}".format(p.name))
        print('+*+')
        saver = self.pretrain_saver
        ckpt = tf.train.get_checkpoint_state(checkpoint_dir=ckpt_dir)
        if not ckpt or not ckpt.model_checkpoint_path:
            print('! PANIC: View {} was not restored by checkpoint in {}'.format(saver.view, ckpt_dir))
            return False
        saver.restore(sess, ckpt.model_checkpoint_path)
        print('Restored Pretrained Weights from {}'.format(ckpt.model_checkpoint_path))
        return True

    def vote(self, local_pred):
        '''
        local_pred: shape [BATCH, VIEW, N]
        return world_pred: shape [BATCH, 1, N], pretending it's still single view.
        '''
        if self.pm is None:
            assert self.view_num == 1
            return local_pred
        assert self.view_num == len(self.pm), "permuation_matrix does not match view number"
        print("local pred {}".format(local_pred.shape))
        local_preds = tf.unstack(local_pred, axis=1) # [BATCH, N] * VIEW
        world_preds = []
        for V in range(self.view_num):
            '''
            td = tf.tensordot(local_preds[V], self.pm_tensor[V],
                              axes=[[1], [1]])
            '''
            td = tf.tensordot(local_preds[V], self.pm_tensor[V], axes=1)
            world_preds.append(td)
        st = tf.stack(world_preds, 1) # Pack VIEW predicts back to [B,V,N] shape
        print("stacked world_preds {}".format(st.shape))
        ret = tf.reduce_sum(st, axis=1, keepdims=True) # To [B,1,N]
        print("voted world_preds {}".format(ret.shape))
        return ret

    def get_local_action(self, action_tensor):
        if self.pm is None:
            return action_tensor
        local_actions = []
        flat_action = action_tensor[:,0,:]
        for V in range(self.view_num):
            la = tf.tensordot(flat_action, self.ipm_tensor[V], axes=1)
            local_actions.append(la)
        return tf.stack(local_actions, 1)

    def get_inverse_model(self):
        if self.inverse_output_tensor is not None:
            return self.inverse_model_params, self.inverse_output_tensor
        input_featvec = tf.concat([self.cur_featvec, self.next_featvec], 2)
        print('inverse_model input {}'.format(input_featvec))
        # featnums = [config.INVERSE_MODEL_HIDDEN_LAYER, int(self.action_tensor.shape[-1])]
        # featnums = config.INVERSE_MODEL_HIDDEN_LAYER + [int(self.action_tensor.shape[-1])]
        featnums = self.imhidden_params + [self.action_space_dimension]
        print('inverse_model featnums {}'.format(featnums))
        self.inverse_fc_applier = vision.ConvApplier(None, featnums, 'InverseModelNet', self.elu)
        params, out = self.inverse_fc_applier.infer(input_featvec)
        self.inverse_model_params = params
        self.inverse_output_tensor = self.vote(out)
        return params, out

    def get_forward_model(self, jointfw=False, output_fn=-1):
        if self.forward_output_tensor is not None:
            return self.forward_model_params, self.forward_output_tensor
        '''
        our pipeline use [None, V, N] feature vector
        3D tensor unifies per-view tensors and combined-view tensors.
        '''
        if jointfw:
            '''
            Joint Prediction of V views
            Expecting better accuracy with V^2 size of network.
            '''
            V=int(self.cur_featvec.shape[1])
            N=int(self.cur_featvec.shape[2])
            input_featvec = tf.reshape(self.cur_featvec, [-1, 1, V*N])
            atensor = self.action_tensor
            name = 'JointForwardModelNet'
        else:
            '''
            Without --jointfw, get_local_action would generate action in local
            coord. sys. and then get_forward_model() predicts each view individually
            '''
            atensor = self.get_local_action(self.action_tensor)
            input_featvec = self.cur_featvec
            name = 'ForwardModelNet'
        featnums = self.fwhidden_params
        if output_fn <= 0:
            featnums += [int(input_featvec.shape[-1])]
        else:
            featnums += [output_fn]
        featvec_plus_action = tf.concat([atensor, input_featvec], 2)
        self.forward_fc_applier = vision.ConvApplier(None, featnums, name, self.elu, nolu_at_final=True)
        # FIXME: ConvApplier.infer returns tuples, which is unsuitable for Optimizer
        params, out = self.forward_fc_applier.infer(featvec_plus_action)
        if jointfw:
            if output_fn <= 0:
                out = tf.reshape(out, [-1, V, N])
            else:
                pass # Return [-1, 1, output_fn] as requested
        self.forward_model_params = params
        self.forward_output_tensor = out
        print('FWD Params {}'.format(params))
        params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=name)
        print('FWD Collected Params {}'.format(params))
        return params, out

    def get_nn_params(self):
        ret = [self.cur_nn_params]
        params, _ = self.get_inverse_model()
        ret.append(params)
        params, _ = self.get_forward_model()
        ret.append(params)
        return sum(ret, [])

    def get_inverse_loss(self, discrete=False):
        _, out = self.get_inverse_model()
        print('inv loss out.shape {}'.format(out.shape))
        print('inv loss action.shape {}'.format(out.shape))
        if not discrete:
            return tf.norm(out - self.action_tensor)
        # TODO: with tf.squeeze ?
        '''
        ret = tf.nn.softmax_cross_entropy_with_logits(
            labels=self.action_tensor,
            logits=out)
        '''
        labels = tf.reshape(self.action_tensor, [-1, self.action_space_dimension])
        logits = tf.reshape(out, [-1, self.action_space_dimension])
        ret = tf.losses.softmax_cross_entropy(
            onehot_labels=labels,
            logits=logits)
        '''
        ret = tf.losses.sigmoid_cross_entropy(
            multi_class_labels=labels,
            logits=logits)
        '''
        print('inv loss ret shape {}'.format(ret.shape))
        return ret

    def get_forward_loss(self, discrete=True):
        assert discrete == True
        _, pred = self.get_forward_model()
        error = pred - self.next_featvec
        loss = tf.nn.l2_loss(error)
        print('forward err shape {}'.format(error.shape))
        print('forward loss shape {}'.format(loss.shape))
        return loss

    class LSTMCache:
        pass

    def create_somenet_from_feature(self, hidden, netname, elu, lstm,
            initialized_as_zero=False,
            nolu_at_final=False,
            batch_normalization=None):
        # featvec = self.cur_featvec
        '''
        Note flattened multi-view feature vector [B, 1, F*V] should be used
        '''
        featvec = self.cur_mvfeatvec
        if lstm is True:
            featvec = self.get_lstm_featvec('LSTM', featvec)
        net = vision.ConvApplier(None, hidden, netname, elu,
                initialized_as_zero=initialized_as_zero,
                nolu_at_final=nolu_at_final,
                batch_normalization=batch_normalization)
        _, out = net.infer(featvec)
        '''
        TODO: Check if this returns LSTM as well (probably not)
        '''
        params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=netname)
        print('{} Params {}'.format(netname, params))
        print('LSTM Params {}'.format(self.acquire_lstm_params()))
        return out, params, [net]

    '''
    Return the tensor of the feature vector, shape [TIME, VIEW (as BATCH), feature]
    Note: we need lstm.states_in in feed_dict if lstm=True
    '''
    def get_lstm_featvec(self, netname, fv):
        if netname in self.lstm_dic:
            return self.lstm_dic[netname].outs
        with tf.variable_scope(netname) as scope:
            print('[LSTM] fv shape {}'.format(fv.shape))
            lstmin = tf.reshape(fv, [1, -1, self.featnum])
            print('[LSTM] lstmin shape {}'.format(lstmin.shape))
            lstm = self.LSTMCache()
            lstm.cell = tf.contrib.rnn.BasicLSTMCell(self.lstmsize, state_is_tuple=True)
            lstm.cell_state_in = tf.placeholder(tf.float32, [1, self.lstmsize], name='LSTMCellInPh')
            lstm.hidden_state_in = tf.placeholder(tf.float32, [1, self.lstmsize], name='LSTMHiddenInPh')
            lstm.init_states_in = tf.contrib.rnn.LSTMStateTuple(lstm.cell_state_in, lstm.hidden_state_in)
            lstm.seq_length_in = tf.placeholder(tf.int32, name='LSTMLenInPh')
            lstm.outs, lstm.states_out = tf.nn.dynamic_rnn(
                    cell=lstm.cell,
                    inputs=fv,
                    initial_state=lstm.init_states_in,
                    sequence_length=lstm.seq_length_in,
                    time_major=True,
                    scope=scope)
        self.lstm_dic[netname] = lstm
        return lstm.outs

    '''
    Must be called AFTER get_lstm_featvec
    '''
    def acquire_lstm_io(self, netname):
        lstm = self.lstm_dic[netname]
        return lstm.init_states_in, lstm.seq_length_in, lstm.states_out

    def acquire_lstm_params(self):
        return tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='LSTM')

def view_scope_name(i):
    return 'ICM_View{}'.format(i)

'''
XXX: THIS CLASS IS SUBJECT TO UPGRADES

IntrinsicCuriosityModuleCommittee:
    ICM Committe, each NN for one view
    Inverse model: accumulating prediction from views as multi-view prediction.
    Forward model: TODO
'''
class IntrinsicCuriosityModuleCommittee:
    icms = None
    view_num = 0
    inverse_output_tensor = None
    forward_output_tensor = None

    def __init__(self,
            action_tensor,
            rgb_tensor,
            depth_tensor,
            next_rgb_tensor,
            next_depth_tensor,
            svconfdict,
            mvconfdict,
            featnum,
            elu,
            ferev=1):
        print('! IntrinsicCuriosityModuleCommittee')
        self.icms = []
        self.view_num = int(rgb_tensor.shape[1])
        self.perview_rgbs_1 = tf.split(rgb_tensor, self.view_num, axis=1)
        self.perview_deps_1 = tf.split(depth_tensor, self.view_num, axis=1)
        self.perview_rgbs_2 = tf.split(next_rgb_tensor, self.view_num, axis=1)
        self.perview_deps_2 = tf.split(next_depth_tensor, self.view_num, axis=1)
        self.action_tensor = action_tensor
        cur_nn_paramss = []
        next_nn_paramss = []
        for i in range(self.view_num):
            with tf.variable_scope(view_scope_name(i)):
                self.icms.append(IntrinsicCuriosityModule(
                    action_tensor,
                    self.perview_rgbs_1[i],
                    self.perview_deps_1[i],
                    self.perview_rgbs_2[i],
                    self.perview_deps_2[i],
                    svconfdict,
                    mvconfdict,
                    featnum=featnum,
                    elu=elu,
                    ferev=ferev))
                cur_nn_paramss.append(self.icms[-1].cur_nn_params)
                next_nn_paramss.append(self.icms[-1].next_nn_params)
        self.cur_nn_params = sum(cur_nn_paramss, [])
        self.next_nn_params = sum(next_nn_paramss, [])

    def get_inverse_model(self):
        if self.inverse_output_tensor is not None:
            return self.inverse_model_params, self.inverse_output_tensor
        paramss = []
        outs = []
        for i in range(self.view_num):
            icm = self.icms[i]
            with tf.variable_scope(view_scope_name(i)):
                params, out = icm.get_inverse_model()
                paramss.append(params)
                outs.append(out)
        self.inverse_model_params = sum(paramss, [])
        self.inverse_output_tensor = tf.add_n(outs)
        return self.inverse_model_params, self.inverse_output_tensor

    def get_forward_model(self):
        if self.forward_output_tensor is not None:
            return self.forward_model_params, self.forward_output_tensor
        pass

    def get_inverse_loss(self, discrete=True):
        assert discrete == True
        _, out = self.get_inverse_model()
        print('> inv loss out.shape {}'.format(out.shape))
        print('> inv loss action.shape {}'.format(out.shape))
        labels = tf.reshape(self.action_tensor, [-1, 12])
        logits = tf.reshape(out, [-1, 12])
        ret = tf.losses.softmax_cross_entropy(
            onehot_labels=labels,
            logits=logits)
        print('inv loss ret shape {}'.format(ret.shape))
        return ret

class IntrinsicCuriosityModuleIndependentCommittee:
    '''
    TODO: A wrapper class to handle multiple ICMs
    Note: this class is slightly different from
          IntrinsicCuriosityModuleCommittee. It does not train multiple ICMs simultaneously.
    '''
    icms = None
    savers = None
    view_num = 0
    inverse_output_tensor = None
    forward_output_tensor = None
    forward_model_params = None
    forward_loss = None
    singlesoftmax = False

    def __init__(self,
            action_tensor,
            rgb_tensor,
            depth_tensor,
            next_rgb_tensor,
            next_depth_tensor,
            svconfdict,
            mvconfdict,
            featnum,
            elu,
            ferev,
            imhidden,
            fehidden,
            singlesoftmax=False):
        print('! IntrinsicCuriosityModuleIndependentCommittee')
        self.icms = []
        self.savers = []
        self.view_num = int(rgb_tensor.shape[1])
        self.perview_rgbs_1 = tf.split(rgb_tensor, self.view_num, axis=1)
        self.perview_deps_1 = tf.split(depth_tensor, self.view_num, axis=1)
        self.perview_rgbs_2 = tf.split(next_rgb_tensor, self.view_num, axis=1)
        self.perview_deps_2 = tf.split(next_depth_tensor, self.view_num, axis=1)
        self.action_tensor = action_tensor
        print('! ICM IC FEREV {}'.format(ferev))
        for i in range(self.view_num):
            with tf.variable_scope(view_scope_name(i)):
                self.icms.append(IntrinsicCuriosityModule(
                    action_tensor=action_tensor,
                    rgb_tensor=self.perview_rgbs_1[i],
                    depth_tensor=self.perview_deps_1[i],
                    next_rgb_tensor=self.perview_rgbs_2[i],
                    next_depth_tensor=self.perview_deps_2[i],
                    svconfdict=svconfdict,
                    mvconfdict=mvconfdict,
                    featnum=featnum,
                    elu=elu,
                    ferev=ferev,
                    imhidden=imhidden,
                    fehidden=fehidden))
                self.icms[-1].get_inverse_model()
            allvars = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=view_scope_name(i))
            self.savers.append(tf.train.Saver(allvars))
            self.savers[-1].view = i
        self.singlesoftmax = singlesoftmax
        self.cur_featvec_cache = None
        self.next_featvec_cache = None

    def restore(self, sess, ckpts):
        for ckpt_dir, saver in zip(ckpts, self.savers):
            ckpt = tf.train.get_checkpoint_state(checkpoint_dir=ckpt_dir)
            if not ckpt or not ckpt.model_checkpoint_path:
                print('! PANIC: View {} was not restored by checkpoint in {}'.format(saver.view, ckpt_dir))
                return False
            print('Restore View {} from {}'.format(saver.view, ckpt.model_checkpoint_path))
            saver.restore(sess, ckpt.model_checkpoint_path)
        return True

    def get_inverse_model(self):
        '''
        Predicts action according to the predictions from multile ICM
        '''
        if self.inverse_output_tensor is not None:
            '''
            ICM IC does not return params
            '''
            return [], self.inverse_output_tensor
        '''
        Method 1:
            softmax(\sum_{v}softmax(pred_v))
        '''
        preds = []
        for icm in self.icms:
            _, pred = icm.get_inverse_model()
            if self.singlesoftmax:
                preds.append(pred)
            else:
                preds.append(tf.nn.softmax(pred))
        self.inverse_output_tensor = tf.nn.softmax(tf.add_n(preds))
        return [], self.inverse_output_tensor

    def get_inverse_loss(self, discrete=True):
        '''
        Independent Committee is not supposed to return a valid loss operator
         - At least for now
        '''
        return tf.constant(-1, tf.float32, [1])

    def get_forward_model(self):
        if self.forward_output_tensor is not None:
            return self.forward_model_params, self.forward_output_tensor
        paramss = []
        outs = []
        for i in range(self.view_num):
            icm = self.icms[i]
            with tf.variable_scope(view_scope_name(i)):
                params, out = icm.get_forward_model()
                paramss.append(params)
                outs.append(out)
        self.forward_model_params = sum(paramss, [])
        self.forward_output_tensor = tf.concat(outs, axis=1)
        return self.forward_model_params, self.forward_output_tensor

    def get_forward_loss(self, discrete=True):
        assert discrete == True
        if self.forward_loss is not None:
            return self.forward_loss
        fwd_losses = []
        for i in range(self.view_num):
            icm = self.icms[i]
            fwd_losses.append(icm.get_forward_loss())
        self.forward_loss = tf.add_n(fwd_losses)
        return self.forward_loss

    def create_somenet_from_feature(self, hidden, netname):
        outs = []
        nets = []
        paramss = []
        for i in range(self.view_num):
            icm = self.icms[i]
            with tf.variable_scope(netname):
                vsn = 'View_{}'.format(i)
                featvec = icm.cur_featvec
                nets.append(vision.ConvApplier(None, hidden, vsn, elu))
                _, out = nets[-1].infer(featvec)
                outs.append(tf.nn.softmax(out))
                paramss.append()
        out = tf.add_n(outs)
        params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope=netname)
        return out, params, nets

    @property
    def cur_featvec(self):
        if self.cur_featvec_cache is not None:
            return self.cur_featvec_cache
        fvs = []
        for icm in self.icms:
            fvs.append(icm.cur_featvec)
        self.cur_featvec_cache = tf.concat(fvs, axis=1)
        return self.cur_featvec_cache

    @property
    def next_featvec(self):
        if self.next_featvec_cache is not None:
            return self.next_featvec_cache
        fvs = []
        for icm in self.icms:
            fvs.append(icm.next_featvec)
        self.next_featvec_cache = tf.concat(fvs, axis=1)
        return self.next_featvec_cache
