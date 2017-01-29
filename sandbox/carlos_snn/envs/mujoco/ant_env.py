from rllab.envs.base import Step
from rllab.misc.overrides import overrides
from rllab.core.serializable import Serializable
from rllab.misc import logger
from rllab.misc import autoargs
from sandbox.carlos_snn.envs.mujoco.mujoco_env import MujocoEnv_ObsInit as MujocoEnv

from rllab.envs.mujoco.mujoco_env import q_mult, q_inv
import numpy as np
import math


class AntEnv(MujocoEnv, Serializable):
    FILE = 'ant.xml'
    ORI_IND = 3

    @autoargs.arg('ctrl_cost_coeff', type=float,
                  help='cost coefficient for controls')
    def __init__(self,
                 ctrl_cost_coeff=1e-2,  # gym has 1 here!
                 rew_speed=False,  # if True the dot product is taken with the speed instead of the position
                 rew_dir=None,  # (x,y,z) -> Rew=dot product of the CoM SPEED with this dir. Otherwise, DIST to 0
                 ego_obs=False,
                 no_contact=False,
                 sparse=False,
                 *args, **kwargs):
        self.ctrl_cost_coeff = ctrl_cost_coeff
        self.reward_dir = rew_dir
        self.rew_speed = rew_speed
        self.ego_obs = ego_obs
        self.no_cntct = no_contact
        self.sparse = sparse

        super(AntEnv, self).__init__(*args, **kwargs)
        Serializable.quick_init(self, locals())

    def get_current_obs(self):
        if self.ego_obs:
            return np.concatenate([
                self.model.data.qpos.flat[2:],
                self.model.data.qvel.flat,
            ]).reshape(-1)
        elif self.no_cntct:
            return np.concatenate([
                self.model.data.qpos.flat,
                self.model.data.qvel.flat,
                self.get_body_xmat("torso").flat,
                self.get_body_com("torso"),
            ]).reshape(-1)
        else:
            return np.concatenate([
                self.model.data.qpos.flat,
                self.model.data.qvel.flat,
                np.clip(self.model.data.cfrc_ext, -1, 1).flat,
                self.get_body_xmat("torso").flat,
                self.get_body_com("torso"),
            ]).reshape(-1)

    @overrides
    def get_ori(self):
        ori = [0, 1, 0, 0]
        rot = self.model.data.qpos[self.__class__.ORI_IND:self.__class__.ORI_IND + 4]  # take the quaternion
        ori = q_mult(q_mult(rot, ori), q_inv(rot))[1:3]  # project onto x-y plane
        ori = math.atan2(ori[1], ori[0])
        return ori

    def step(self, action):
        self.forward_dynamics(action)
        if self.rew_speed:
            direction_com = self.get_body_comvel('torso')
        else:
            direction_com = self.get_body_com('torso')
        if self.reward_dir:
            direction = np.array(self.reward_dir, dtype=float) / np.linalg.norm(self.reward_dir)
            forward_reward = np.dot(direction, direction_com)
        else:
            forward_reward = np.linalg.norm(
                direction_com[0:-1])  # instead of comvel[0] (does this give jumping reward??)
        lb, ub = self.action_bounds
        scaling = (ub - lb) * 0.5
        ctrl_cost = 0.5 * self.ctrl_cost_coeff * np.sum(np.square(action / scaling))
        contact_cost = 0.5 * 1e-3 * np.sum(
            np.square(np.clip(self.model.data.cfrc_ext, -1, 1)))
        survive_reward = 0.05  # this is not in swimmer neither!! And in the GYM env it's 1!!!

        if self.sparse:
            if np.linalg.norm(self.get_body_com("torso")[0:2]) > np.inf:  # potentially could specify some distance
                reward = 1.0
            else:
                reward = 0.
        else:
            reward = forward_reward - ctrl_cost - contact_cost + survive_reward

        # print("Forward reward: {}\nCtrl_cost: {}\nContact_cost: {}\n".format(forward_reward, ctrl_cost, contact_cost))
        state = self._state
        notdone = np.isfinite(state).all() \
                  and state[2] >= 0.3 and state[2] <= 1.0  # this was 0.2 and 1.0
        done = not notdone
        ob = self.get_current_obs()
        com = np.concatenate([self.get_body_com("torso").flat]).reshape(-1)
        ori = self.get_ori()
        return Step(ob, float(reward), done,
                    com=com, ori=ori, forward_reward=forward_reward, ctrl_cost=ctrl_cost,
                    contact_cost=contact_cost, survive_reward=survive_reward)

    @overrides
    def log_diagnostics(self, paths, prefix=''):
        progs = [
            np.linalg.norm(path["env_infos"]["com"][-1] - path["env_infos"]["com"][0])
            for path in paths
            ]
        logger.record_tabular('AverageForwardProgress', np.mean(progs))
        logger.record_tabular('MaxForwardProgress', np.max(progs))
        logger.record_tabular('MinForwardProgress', np.min(progs))
        logger.record_tabular('StdForwardProgress', np.std(progs))
        self.plot_visitations(paths, visit_prefix=prefix)
