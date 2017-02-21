import random
from rllab import spaces
import sys
import os.path as osp
import matplotlib as mpl

mpl.use('Agg')
import matplotlib.pyplot as plt

import numpy as np
import math

from rllab.envs.mujoco.mujoco_env import MODEL_DIR, BIG
from rllab.core.serializable import Serializable
from rllab.envs.proxy_env import ProxyEnv
from rllab.envs.base import Step
from rllab.misc import autoargs
from rllab.misc import logger
from rllab.misc.overrides import overrides


class InitGenerator(object):
    """ Base class for goal generator. """

    def __init__(self):
        self._init = None
        self.update()

    def update(self):
        return self.init

    @property
    def init(self):
        return self._init


class UniformListInitGenerator(InitGenerator, Serializable):
    """ Generating goals uniformly from a goal list. """

    def __init__(self, init_list):
        Serializable.quick_init(self, locals())
        self.init_list = init_list
        self.init_size = np.size(self.init_list[0])  # assumes all goals have same dim as first in list
        random.seed()
        super(UniformListInitGenerator, self).__init__()

    def update(self):
        self._init = random.choice(self.init_list)
        return self.init


class UniformInitGenerator(InitGenerator, Serializable):
    """ Generating goals uniformly inside a hyper-rectangle around the center (like the desired goal). """

    def __init__(self, init_size, bound=2, center=()):
        Serializable.quick_init(self, locals())
        self.init_size = init_size
        self.bound = bound
        self.center = center if len(center) else np.zeros(self.init_size)
        super(UniformInitGenerator, self).__init__()

    def update(self):  # This should be centered around the initial position!!
        self._init = self.center + np.random.uniform(low=-self.bound, high=self.bound, size=self.init_size)
        return self.init


class FixedInitGenerator(InitGenerator, Serializable):
    """ Generating a fixed goal. """

    def __init__(self, init):
        Serializable.quick_init(self, locals())
        super(FixedInitGenerator, self).__init__()
        self._init = init


class InitEnv(Serializable):
    """ Base class for init based environment. Implements init update utilities. """
    def __init__(self, init_generator=None, goal=None):
        """
        :param init_generator: generator of initial positions
        :param goal: point in state-space that gives a reward
        """
        Serializable.quick_init(self, locals())
        self._init_generator = init_generator
        self.goal = goal

    def reset(self):  # this is a very dumb method here
        return self.current_init

    def update_init_generator(self, init_generator):
        self._init_generator = init_generator

    def update_init(self):
        return self.init_generator.update()

    @property
    def init_generator(self):
        return self._init_generator

    @property
    def current_init(self):
        return self.init_generator.init

    @property
    def current_goal(self):
        return self.goal

    def __getstate__(self):
        d = super(InitEnv, self).__getstate__()
        d['__init_generator'] = self.init_generator
        return d

    def __setstate__(self, d):
        super(InitEnv, self).__setstate__(d)
        self.update_init_generator(d['__init_generator'])


class InitEnvAngle(InitEnv, Serializable):

    def __init__(self, angle_idxs=(None,), **kwargs):
        """Indicates the coordinates that are angles and need to be duplicated to cos/sin"""
        Serializable.quick_init(self, locals())
        self.angle_idxs = angle_idxs
        super(InitEnvAngle, self).__init__(**kwargs)

    @overrides
    @property
    def current_init(self):
        # print("the init generator is:", self.init_generator)
        angle_init = self.init_generator.init
        full_init = []
        for i, coord in enumerate(angle_init):
            if i in self.angle_idxs:
                full_init.extend([np.sin(coord), np.cos(coord)])
            else:
                full_init.append(coord)
        # print("the angle init is: {}, the full init is: {}".format(angle_init, full_init))
        return full_init

    @overrides
    @property
    def current_goal(self):
        # print("the init generator is:", self.init_generator)
        angle_goal = self.goal
        full_goal = []
        for i, coord in enumerate(angle_goal):
            if i in self.angle_idxs:
                full_goal.extend([np.sin(coord), np.cos(coord)])
            else:
                full_goal.append(coord)
                # print("the angle init is: {}, the full init is: {}".format(angle_goal, full_goal))
        return full_goal


class InitExplorationEnv(InitEnvAngle, ProxyEnv, Serializable):
    def __init__(self, env, init_generator, goal, append_goal=False, terminal_bonus=0, terminal_eps=0.1,
                 distance_metric='L2', goal_reward='NegativeDistance', goal_weight=1,
                 inner_weight=0, angle_idxs=(None,)):
        """
        :param env: wrapped env
        :param init_generator: already instantiated: NEEDS GOOD DIM OF GOALS! --> TO DO: give the class a method to update dim?
        :param terminal_bonus: if not 0, the rollout terminates with this bonus if the goal state is reached
        :param terminal_eps: eps around which the terminal goal is considered reached
        :param distance_metric: L1 or L2 or a callable func
        :param goal_reward: NegativeDistance or InverseDistance or callable func
        :param goal_weight: coef of the goal-dist reward
        :param inner_weight: coef of the inner reward
        """

        Serializable.quick_init(self, locals())
        self.append_goal = append_goal
        self.terminal_bonus = terminal_bonus
        self.terminal_eps = terminal_eps
        self._distance_metric = distance_metric
        self._goal_reward = goal_reward
        self.goal_weight = goal_weight
        self.inner_weight = inner_weight
        self.fig_number = 0
        ProxyEnv.__init__(self, env)
        InitEnvAngle.__init__(self, angle_idxs=angle_idxs, init_generator=init_generator, goal=goal)

    def reset(self, reset_init=True, reset_inner=True):
        if reset_init:
            self.update_init()
        if reset_inner:
            self.wrapped_env.reset(initial_state=self.current_init)
        obs = self.get_current_obs()
        return self.get_current_obs()

    def step(self, action):
        observation, reward, done, info = ProxyEnv.step(self, action)
        info['reward_inner'] = reward_inner = self.inner_weight * reward
        info['distance'] = dist = self._compute_dist(observation)
        info['reward_dist'] = reward_dist = self._compute_dist_reward(observation)
        if self.terminal_bonus and dist <= self.terminal_eps:
            # print("*****done!!*******")
            done = True
            reward_dist += self.terminal_bonus
        return (
            self.get_current_obs(),
            reward_dist + reward_inner,
            done,
            info
        )

    def _compute_dist_reward(self, obs):
        goal_distance = self._compute_dist(obs)
        if self._goal_reward == 'NegativeDistance':
            intrinsic_reward = - goal_distance
        elif self._goal_reward == 'InverseDistance':
            intrinsic_reward = 1. / (goal_distance + 0.1)
        elif callable(self._goal_reward):
            intrinsic_reward = self._goal_reward(goal_distance)
        else:
            raise NotImplementedError('Unsupported goal_reward type.')

        return self.goal_weight * intrinsic_reward

    def _compute_dist(self, obs):
        if self._distance_metric == 'L1':
            goal_distance = np.sum(np.abs(obs - self.current_goal))
        elif self._distance_metric == 'L2':
            goal_distance = np.sqrt(np.sum(np.square(obs - self.current_goal)))
        elif callable(self._distance_metric):
            goal_distance = self._distance_metric(obs, self.current_goal)
        else:
            raise NotImplementedError('Unsupported distance metric type.')
        return goal_distance

    def get_current_obs(self):
        obj = self
        while hasattr(obj, "wrapped_env"):  # try to go through "Normalize and Proxy and whatever wrapper"
            obj = obj.wrapped_env
        if self.append_goal:
            return self._append_observation(obj.get_current_obs())
        else:
            return obj.get_current_obs()

    def _append_observation(self, obs):
        return np.concatenate([obs, np.array(self.current_goal)])

    @property
    @overrides
    def observation_space(self):
        shp = self.get_current_obs().shape
        ub = BIG * np.ones(shp)
        return spaces.Box(ub * -1, ub)

    @overrides
    def log_diagnostics(self, paths, fig_prefix='', *args, **kwargs):
        if fig_prefix == '':
            fig_prefix = str(self.fig_number)
            self.fig_number +=1
        # Process by time steps
        distances = [
            np.mean(path['env_infos']['distance'])
            for path in paths
            ]
        initial_goal_distances = [
            path['env_infos']['distance'][0] for path in paths
            ]
        reward_dist = [
            np.mean(path['env_infos']['reward_dist'])
            for path in paths
            ]
        reward_inner = [
            np.mean(path['env_infos']['reward_inner'])
            for path in paths
            ]
        success = [int(np.min(path['env_infos']['distance']) <= self.terminal_eps) for path in paths]
        print(success)

        # Can I also log the goal_success rate??

        # Process by trajectories
        logger.record_tabular('InitGoalDistance', np.mean(initial_goal_distances))
        logger.record_tabular('MeanDistance', np.mean(distances))
        logger.record_tabular('MeanRewardDist', np.mean(reward_dist))
        logger.record_tabular('MeanRewardInner', np.mean(reward_inner))
        logger.record_tabular('SuccessRate', np.mean(success))

        # The goal itself is prepended to the observation, so we can retrieve the collection of goals:
        full_goal_dim = np.size(self.current_goal)
        if self.append_goal:
            inits = [path['observations'][0][:-full_goal_dim] for path in paths]  # supposes static goal over whole paths
        else:
            inits = [path['observations'][0] for path in paths]  # supposes static goal over whole paths
        angle_inits = [math.atan2(init[0], init[1]) for init in inits]
        angVel_inits = [init[2] for init in inits]
        colors = ['g'*succ + 'r'*(1-succ) for succ in success]
        fig, ax = plt.subplots()
        ax.scatter(angle_inits, angVel_inits, c=colors, lw=0)
        log_dir = logger.get_snapshot_dir()
        plt.savefig(osp.join(log_dir, fig_prefix + 'init_performance.png'))
        plt.close()


class InitIdxExplorationEnv(InitExplorationEnv, Serializable):
    """
    Instead of using the full state-space as goal, this class uses the observation[-3,-1] CoM in MuJoCo
    """

    def __init__(self, idx=(-3, -2), **kwargs):
        Serializable.quick_init(self, locals())
        self.idx = idx
        super(InitIdxExplorationEnv, self).__init__(**kwargs)

    def step(self, action):
        observation, reward, done, info = ProxyEnv.step(self, action)
        info['reward_inner'] = reward_inner = self.inner_weight * reward
        body_com = observation[self.idx,]
        info['distance'] = np.linalg.norm(body_com - self.current_init)
        reward_dist = self._compute_dist_reward(body_com)
        info['reward_dist'] = reward_dist
        return (
            self.get_current_obs(),
            reward_dist + reward_inner,
            done,
            info
        )
