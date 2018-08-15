from curiosity import CuriosityRL
from curiosity import RigidPuzzle as AlphaPuzzle
import pyosr
import numpy as np
from rlreanimator import reanimate
import uw_random
from six.moves import input
import progressbar
import rlcaction

def _press_enter():
    print("#############################################")
    print("##########CONGRATS TERMINAL REACHED##########")
    print("########## PRESS ENTER TO CONTINUE ##########")
    input("#############################################")

'''
Base class to visualize/evaluate the RL training results
'''
class RLVisualizer(object):
    def __init__(self, args, g, global_step):
        self.args = args
        self.dpy = pyosr.create_display()
        self.ctx = pyosr.create_gl_context(self.dpy)
        self.envir = AlphaPuzzle(args, 0)
        self.envir.egreedy = 0.995
        self.uw = self.envir.r
        self.r = self.envir.r
        self.advcore = CuriosityRL(learning_rate=1e-3, args=args)
        self.advcore.softmax_policy # Create the tensor
        self.gview = 0 if args.obview < 0 else args.obview
        if args.permutemag >= 0:
            self.envir.enable_perturbation(args.manual_p)
        self.mandatory_ckpt = True

    def attach(self, sess):
        self.sess = sess

class PolicyPlayer(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(PolicyPlayer, self).__init__(args, g, global_step)

    def play(self):
        reanimate(self)

    def __iter__(self):
        envir = self.envir
        sess = self.sess
        advcore = self.advcore
        reaching_terminal = False
        pprefix = "[0] "
        while True:
            rgb,_ = envir.vstate
            yield rgb[self.gview] # First view
            if reaching_terminal:
                _press_enter()
                envir.reset()
            [policy, value] = advcore.evaluate([envir.vstate], sess, [advcore.softmax_policy, advcore.value])
            policy = policy[0][0]
            value = np.asscalar(value)
            action_index = advcore.make_decision(envir, policy, pprefix)
            print("Current Value {}".format(value))
            print("PolicyPlayer unmasked pol {}".format(policy))
            # print("PolicyPlayer masked pol {}".format(policy * advcore.action_mask))
            print("PolicyPlayer Action Index {}".format(action_index))
            nstate,reward,reaching_terminal,ratio = envir.peek_act(action_index, pprefix=pprefix)
            envir.qstate = nstate

class CriticPlayer(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(CriticPlayer, self).__init__(args, g, global_step)

    def play(self):
        reanimate(self)

    def __iter__(self):
        envir = self.envir
        sess = self.sess
        advcore = self.advcore
        reaching_terminal = False
        pprefix = "[0] "
        while True:
            rgb,_ = envir.vstate
            yield rgb[self.gview] # First view
            if reaching_terminal:
                _press_enter()
                envir.reset()
            qs_bak = envir.qstate
            vs = []
            for a in self.args.actionset:
                nstate,reward,reaching_terminal,ratio = envir.peek_act(a)
                envir.qstate = nstate
                vs.append(envir.vstate)
            envir.qstate = qs_bak
            values = advcore.evaluate(vs, sess, [advcore.value])
            values = np.reshape(values, (-1))
            print("Values {}".format(values))
            ai = np.argmax(values)
            # print("PolicyPlayer unmasked pol {}".format(policy))
            # print("PolicyPlayer masked pol {}".format(policy * advcore.action_mask))
            # print("PolicyPlayer Action Index {}".format(action_index))
            nstate,reward,reaching_terminal,ratio = envir.peek_act(self.args.actionset[ai], pprefix=pprefix)
            envir.qstate = nstate

class QPlayer(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(QPlayer, self).__init__(args, g, global_step)
        if args.permutemag > 0:
            self.envir.enable_perturbation()
        if args.samplein: # User can feed samples through samplein
            self.gt = np.load(args.samplein)
            self.gt_iter = 0
        else:
            self.gt = None

    def render(self, envir, state):
        envir.qstate = state
        return envir.vstate

    def play(self):
        if self.args.sampleout:
            self._sample()
        else:
            self._play()

    def _sample_mini_batch(self, batch):
        if self.gt is None:
            return [uw_random.gen_unit_init_state(envir.r) for i in range(args.batch)]
        states = np.take(self.gt['V'],
                indices=range(self.gt_iter, self.gt_iter + batch),
                axis=0, mode='wrap')
        self.gt_iter += batch
        return [state for state in states] # Convert 2D np.array to list of 1D np.array

    def _sample(self):
        Q = [] # list of states
        V = [] # list of numpy array of batched values
        args = self.args
        sess = self.sess
        advcore = self.advcore
        envir = self.envir
        assert args.iter % args.batch == 0, "presumably --iter is dividable by --batch"
        for i in range(args.iter/args.batch):
            states = self._sample_mini_batch(args.batch)
            Q += states
            images = [self.render(envir, state) for state in states]
            batch_rgb = [image[0] for image in images]
            batch_dep = [image[1] for image in images]
            dic = {
                    advcore.rgb_1: batch_rgb,
                    advcore.dep_1: batch_dep,
                  }
            values = sess.run(advcore.value, feed_dict=dic)
            values = np.reshape(values, [-1]) # flatten
            V.append(values)
        Q = np.array(Q)
        V = np.concatenate(V)
        np.savez(args.sampleout, Q=Q, V=V)

    def _play(self):
        reanimate(self)

    def __iter__(self):
        args = self.args
        sess = self.sess
        advcore = self.advcore
        envir = self.envir
        envir.reset()
        current_value = -1
        TRAJ = []
        while True:
            TRAJ.append(envir.qstate)
            yield envir.vstate[0][args.obview] # Only RGB
            NS = []
            images = []
            # R = []
            T = []
            TAU = []
            state = envir.qstate
            print("> Current State {}".format(state))
            for action in args.actionset:
                envir.qstate = state # IMPORTANT: Restore the state to unpeeked condition
                nstate, reward, terminal, ratio = envir.peek_act(action)
                envir.qstate = nstate
                NS.append(nstate)
                T.append(terminal)
                TAU.append(ratio)
                image = envir.vstate
                images.append(image)
            batch_rgb = [image[0] for image in images]
            batch_dep = [image[1] for image in images]
            dic = {
                    advcore.rgb_1: batch_rgb,
                    advcore.dep_1: batch_dep,
                  }
            values = sess.run(advcore.value, feed_dict=dic)
            values = np.reshape(values, [-1]) # flatten
            best = np.argmax(values, axis=0)
            print("> Current Values {}".format(values))
            print("> Taking Action {} RATIO {}".format(best, TAU[best]))
            print("> NEXT State {} Value".format(NS[best], values[best]))
            envir.qstate = NS[best]
            should_reset = False
            if current_value > values[best] or TAU[best] == 0.0:
                input("FATAL: Hit Local Maximal! Press Enter to restart")
                should_reset = True
            else:
                current_value = values[best]
            if T[best]:
                input("DONE! Press Enter to restart ")
                should_reset = True
            if should_reset:
                fn = input("Enter the filename to save the trajectory ")
                if fn:
                    TRAJ.append(envir.qstate)
                    TRAJ = np.array(TRAJ)
                    np.savez(fn, TRAJ=TRAJ, SINGLE_PERM=envir.get_perturbation())
                envir.reset()
                current_value = -1
                TRAJ = []

class CuriositySampler(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(CuriositySampler, self).__init__(args, g, global_step)
        assert args.visualize == 'curiosity', '--visualize must be curiosity'
        assert args.curiosity_type == 1, "--curiosity_type should be 1 if --visualize is enabled"
        assert args.sampleout != '', '--sampleout must be enabled for --visualize curiosity'

    def play(self):
        args = self.args
        sess = self.sess
        advcore = self.advcore
        envir = self.envir
        samples= []
        curiosities_by_action = [ [] for i in range(uw_random.DISCRETE_ACTION_NUMBER) ]
        for i in range(args.iter):
            state = uw_random.gen_unit_init_state(envir.r)
            envir.qstate = state
            samples.append(state)
            for action in range(uw_random.DISCRETE_ACTION_NUMBER):
                nstate, reward, terminal, ratio = envir.peek_act(action)
                areward = advcore.get_artificial_reward(envir, sess,
                        state, action, nstate, ratio)
                curiosities_by_action[action].append(areward)
        samples = np.array(samples)
        curiosity = np.array(curiosities_by_action)
        np.savez(args.sampleout, Q=samples, C=curiosity)

class Fake3dSampler(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(Fake3dSampler, self).__init__(args, g, global_step)
        assert args.sampleout, '--visualize fake3d requires --sampleout'
        self.istate = np.array(self.r.translate_to_unit_state(args.istateraw), dtype=np.float32)
        if 10 in args.actionset or 11 in args.actionset:
            self.has_rotation = True
        else:
            self.has_rotation = False
        self.zaxis_row = np.array([[0,0,1]],dtype=np.float32)

    def _sample(self, scale = 5.0):
        while True:
            quat = np.array([1, 0, 0, 0], dtype=np.float32)
            if self.has_rotation:
                theta = np.random.rand() * np.pi
                quat[0] = np.cos(theta) # * 0.5 was cancelled since we sampled from [0,pi)
                quat[3] = np.sin(theta) # rotation around z axis, hence [1,2] == 0
            tr = scale * (np.random.rand(3) - 0.5)
            tr[2] = self.istate[2] # Fix at the same plane
            state = np.concatenate((tr, quat))
            if self.r.is_disentangled(state):
                continue
            if self.r.is_valid_state(state):
                return state

    '''
    Sample in 2D space and convert it to 3D
    '''
    def _sample_mini_batch(self, batch):
        ret = []
        for i in range(batch):
            ret.append(self._sample())
        return ret

    def render(self, envir, state):
        envir.qstate = state
        return envir.vstate

    def play(self):
        args = self.args
        advcore = self.advcore
        envir = self.envir
        sess = self.sess
        Q = []
        V = []
        Po = []
        for i in progressbar.progressbar(range(args.iter / args.batch)):
            qbatch = self._sample_mini_batch(args.batch)
            images = [self.render(envir, state) for state in qbatch]
            batch_rgb = [image[0] for image in images]
            batch_dep = [image[1] for image in images]
            dic = {
                    advcore.rgb_1: batch_rgb,
                    advcore.dep_1: batch_dep,
                  }
            policies, values = sess.run([advcore.softmax_policy, advcore.value], feed_dict=dic)
            values = np.reshape(values, [-1]) # flatten
            policies = np.reshape(policies, [-1, advcore.action_space_dimension]) #
            Q += qbatch
            V.append(values)
            Po.append(policies)
        Q = np.array(Q)
        V = np.concatenate(V)
        Po = np.concatenate(Po)
        np.savez(args.sampleout, Q=Q, V=V, Po=Po)

'''
Milestome To State Action sampler
'''
class MSASampler(RLVisualizer):
    def __init__(self, args, g, global_step):
        super(MSASampler, self).__init__(args, g, global_step)
        assert args.msiraw, '--visualize msa requires --msiraw as input'
        assert args.sampleout, '--visualize msa requires --sampleout'
        msraw = np.array(args.msiraw)
        self.msraw = np.reshape(msraw, (-1, 7))
        assert self.msraw[0].all() == np.array(args.msiraw[:7]).all(), "--msiraw reshaped well"
        ms = []
        for msraw in self.msraw:
            ms.append(np.array(self.r.translate_to_unit_state(msraw), dtype=np.float32))
        self.ms = np.array(ms, dtype=np.float32)
        # self.traj_s = []
        # self.traj_a = []
        # self.traj_fv = []
        self.mandatory_ckpt = False

    def play(self):
        reanimate(self)

    def _fv(self):
        advcore = self.advcore
        envir = self.envir
        sess = self.sess
        return advcore.evaluate([envir.vstate], sess, advcore.model.cur_featvec)

    def __iter__(self):
        envir = self.envir
        sess = self.sess
        reaching_terminal = False
        args = self.args
        pprefix = "[0] "
        traj_s = [envir.qstate]
        traj_a = []
        traj_fv = [self._fv()]
        print("Initial state {}".format(envir.qstate))
        print("MS list {}".format(self.ms))
        rgb,_ = envir.vstate
        yield rgb[self.gview] # First view
        for ms in self.ms:
            print("Switch MS to {}".format(ms))
            while True:
                print("Current state {}".format(envir.qstate))
                sa = []
                sd = []
                rt = []
                rw = []
                for a in args.actionset:
                    nstate,r,reaching_terminal,_ = envir.peek_act(a)
                    sa.append(nstate)
                    sd.append(pyosr.distance(nstate, ms))
                    rw.append(r)
                    rt.append(reaching_terminal)
                print("sa {} \nsd {}".format(sa, sd))
                ai = np.argmin(sd)
                if sd[ai] > pyosr.distance(envir.qstate, ms): # Local minimum reached
                    break
                a = args.actionset[ai]
                traj_a.append(a)
                envir.qstate = sa[ai]
                traj_s.append(envir.qstate)
                traj_fv.append(self._fv())
                rgb,_ = envir.vstate
                if rw[ai] < 0:
                    print("#############################################")
                    print("!!!!!!!!!!   CRITICAL: COLLISION   !!!!!!!!!!")
                    print("!!!!!!!!!!   PRESS ENTER TO EXIT   !!!!!!!!!!")
                    input("#############################################")
                    np.savez(args.sampleout+'.die',
                             TRAJ_S=traj_s,
                             TRAJ_A=traj_a,
                             TRAJ_FV=traj_fv)
                    return
                    yield
                if rt[ai]:
                    _press_enter()
                    np.savez(args.sampleout,
                             TRAJ_S=traj_s,
                             TRAJ_A=traj_a,
                             TRAJ_FV=traj_fv)
                    return
                    yield
                yield rgb[self.gview] # First view

class CActionPlayer(RLVisualizer):
    def __init__(self, args, g, global_step, sancheck=False):
        assert args.samplein, '--samplein is mandatory for --visualize caction'
        super(CActionPlayer, self).__init__(args, g, global_step)
        d = np.load(args.samplein)
        self.V = d['V']
        self.N = d['N']
        self.D = d['D']
        self.mandatory_ckpt = False
        self.sancheck = sancheck

    def play(self):
        if self.sancheck:
            self.sanity_check()
        else:
            reanimate(self, fps=30)

    def __iter__(self):
        envir = self.envir
        uw = envir.r
        amag = self.args.amag
        V = self.V
        N = self.N
        D = self.D
        while True:
            if self.args.samplein2:
                VS = np.load(self.args.samplein2)['VS']
                vs = np.array([uw.translate_to_unit_state(v) for v in VS])
                for qs,crt,caa in rlcaction.trajectory_to_caction(vs, uw, amag):
                    envir.qstate = qs
                    rgb,_ = envir.vstate
                    yield rgb[self.gview]
            else:
                for qs,crt,caa in rlcaction.caction_generator(V, N, D, amag, uw):
                    assert envir.r.is_valid_state(qs)
                    envir.qstate = qs
                    rgb,_ = envir.vstate
                    yield rgb[self.gview] # First view
            assert envir.r.is_disentangled(envir.qstate)
            _press_enter()

    def sanity_check(self):
        envir = self.envir
        uw = envir.r
        amag = self.args.amag
        V = self.V
        N = self.N
        D = self.D
        for ivi in progressbar.progressbar(range(len(V))):
            # print("IVI {}".format(ivi))
            vs = rlcaction.ivi_to_leaving_trajectory(ivi, V, N, D, amag, uw)
            if not vs:
                continue
            for qs,crt,caa in rlcaction.trajectory_to_caction(vs, uw, amag):
                assert envir.r.is_valid_state(qs)

class CActionPlayer2(RLVisualizer):
    def __init__(self, args, g, global_step, sancheck=False):
        assert args.samplein, '--samplein is mandatory for --visualize caction2'
        super(CActionPlayer2, self).__init__(args, g, global_step)
        self.mandatory_ckpt = False
        VS = np.load(self.args.samplein)['VS']
        # print("ALLVS {}".format(VS))
        uw = self.envir.r
        self.known_path = [uw.translate_to_unit_state(v) for v in VS]
        self.out_index = 0

    def play(self):
        reanimate(self, fps=30)

    def __iter__(self):
        envir = self.envir
        uw = envir.r
        amag = self.args.amag
        out_dir = self.args.sampleout
        while True:
            QS = []
            CTR = []
            CAA = []
            for qs,ctr,caa in rlcaction.caction_generator2(uw, self.known_path, 0.15, amag):
            #for qs,crt,caa in rlcaction.trajectory_to_caction(self.known_path, uw, amag):
                QS.append(qs)
                CTR.append(ctr)
                CAA.append(caa)
                assert envir.r.is_valid_state(qs)
                # print('qs {}'.format(qs))
                # print('ctr {}'.format(ctr))
                # print('caa {}'.format(caa))
                envir.qstate = qs
                rgb,_ = envir.vstate
                yield rgb[self.gview]
            # assert envir.r.is_disentangled(envir.qstate)
            if out_dir:
                fn = '{}/{}.npz'.format(out_dir, self.out_index)
                '''
                print("QS {}".format(QS))
                print("CTR {}".format(CTR))
                print("CAA {}".format(CAA))
                print("lengths {} {} {}".format(len(QS), len(CTR), len(CAA)))
                print("### SAVING TO {}".format(fn))
                QS = np.array(QS)
                print("QS {}".format(QS))
                CTR = np.array(CTR)
                print("CTR {}".format(CTR))
                CAA = np.array(CAA)
                print("CAA {}".format(CAA))
                print('sizes {} {} {}'.format(QS.shape, CTR.shape, CAA.shape))
                '''
                np.savez(fn, QS=QS, CTR=CTR, CAA=CAA)
                print("### {} SAVED".format(fn))
                self.out_index += 1
                '''
                if self.args.iter > 0 and self.out_index > self.args.iter:
                    return
                '''
            else:
                _press_enter()

class CActionPlayer2ISFinder(RLVisualizer):
    def __init__(self, args, g, global_step, sancheck=False):
        assert args.samplein, '--samplein is mandatory for --visualize caction2_istate_finder'
        assert args.sampleout, '--sampleout is mandatory for --visualize caction2_istate_finder'
        super(CActionPlayer2ISFinder, self).__init__(args, g, global_step)
        self.mandatory_ckpt = False
        VS = np.load(self.args.samplein)['VS']
        # print("ALLVS {}".format(VS))
        uw = self.envir.r
        self.known_path = [uw.translate_to_unit_state(v) for v in VS]
        self.out_index = 0


def create_visualizer(args, g, global_step):
    if args.qlearning_with_gt:
        # assert args.sampleout, "--sampleout is required to store the samples for --qlearning_with_gt"
        assert args.iter > 0, "--iter needs to be specified as the samples to generate"
        # assert False, "Evaluating of Q Learning is not implemented yet"
        return QPlayer(args, g, global_step)
    elif args.visualize == 'policy':
        return PolicyPlayer(args, g, global_step)
    elif args.visualize == 'critic':
        return CriticPlayer(args, g, global_step)
    elif args.visualize == 'curiosity':
        return CuriositySampler(args, g, global_step)
    elif args.visualize == 'fake3d':
        return Fake3dSampler(args, g, global_step)
    elif args.visualize == 'msa':
        return MSASampler(args, g, global_step)
    elif args.visualize == 'caction':
        return CActionPlayer(args, g, global_step)
    elif args.visualize == 'caction_sancheck':
        return CActionPlayer(args, g, global_step, sancheck=True)
    elif args.visualize == 'caction2':
        return CActionPlayer2(args, g, global_step)
    elif args.visualize == 'caction2_istate_finder':
        return CActionPlayer2ISFinder(args, g, global_step)
    assert False, '--visualize {} is not implemented yet'.format(args.visualize)
