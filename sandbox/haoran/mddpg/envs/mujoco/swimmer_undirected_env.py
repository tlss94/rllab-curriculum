from rllab.envs.base import Step
from rllab.misc.overrides import overrides
from rllab.envs.mujoco.mujoco_env import MujocoEnv
from rllab.core.serializable import Serializable
from rllab.misc import logger
from rllab.misc import autoargs
from sandbox.haoran.mddpg.policies.mnn_policy import MNNPolicy
from sandbox.haoran.mddpg.policies.nn_policy import NNPolicy
from sandbox.tuomas.mddpg.policies.stochastic_policy import StochasticNNPolicy
import os
import json
import numpy as np
import gc
import matplotlib.pyplot as plt


class SwimmerUndirectedEnv(MujocoEnv, Serializable):

    FILE = 'swimmer.xml'

    def __init__(
            self,
            ctrl_cost_coeff=1e-2,
            visitation_plot_config=None,
            prog_threshold=2.,
            motion_reward=True,
            visitation_reward=False,
            *args, **kwargs):
        self.ctrl_cost_coeff = ctrl_cost_coeff
        self.visitation_plot_config = visitation_plot_config
        self.prog_threshold = prog_threshold

        self.motion_reward = motion_reward
        self.visitation_reward = visitation_reward

        self.visitation_bins = np.zeros((8, 12))
        self.visitation_reward_coeff = 1.
        self.visitation_leak_factor = 0.999

        super(SwimmerUndirectedEnv, self).__init__(*args, **kwargs)
        Serializable.quick_init(self, locals())


    def get_current_obs(self):
        return np.concatenate([
            self.model.data.qpos.flat,
            self.model.data.qvel.flat,
            #self.get_body_com("torso").flat,
        ]).reshape(-1)

    def get_com(self):
        return self.get_body_com("torso").flat[:2]

    def step(self, action):
        self.forward_dynamics(action)
        next_obs = self.get_current_obs()
        lb, ub = self.action_bounds
        scaling = (ub - lb) * 0.5
        action_norm_sq = np.sum(np.square(action / scaling))
        ctrl_cost = 0.5 * self.ctrl_cost_coeff * action_norm_sq
        if (np.abs(action / scaling) > 1).any():
            dist = max((np.abs(action / scaling) - 1).max(), 0)
            ctrl_cost += 1. * dist**2
            #ctrl_cost += 0.1


        done = False
        com = np.concatenate([self.get_body_com("torso").flat]).reshape(-1)

        motion_reward = (
            np.linalg.norm(self.get_body_comvel("torso"))
            if self.motion_reward else 0.0
        )

        visitation_reward = (
            self.get_visitation_reward(com) if self.visitation_reward else 0.0
        )
        reward = motion_reward + visitation_reward - ctrl_cost
            # send the com separately as env_info to avoid problems induced
            # by normalizing the observations

        return Step(next_obs, reward, done, com=com)

    def get_visitation_reward(self, com):
        th = np.arctan2(com[0], com[1]) + np.pi
        dist = np.linalg.norm(com)

        th_bin = int(th / np.pi * 4)
        if th_bin == 8:  # Hacky fix for the corner case.
            th_bin = 1
        dist_bin = int(dist / 1.0)

        self.visitation_bins[th_bin, dist_bin] += 1.
        self.visitation_bins *= self.visitation_leak_factor

        reward =  self.visitation_reward_coeff / (
            self.visitation_bins[th_bin, dist_bin] + 1.)

        return reward

    @overrides
    def log_diagnostics(self, paths):
        progs = []
        for path in paths:
            coms = path["env_infos"]["com"]
            progs.append(coms[-1][0] - coms[0][0])
                # x-coord of com at the last time step minus the 1st step

        logger.record_tabular('env: ForwardProgressAverage', np.mean(progs))
        logger.record_tabular('env: ForwardProgressMax', np.max(progs))
        logger.record_tabular('env: ForwardProgressMin', np.min(progs))
        logger.record_tabular('env: ForwardProgressStd', np.std(progs))
        import pdb; pdb.set_trace()

    def log_stats(self, algo, epoch, paths, ax):
        # forward distance
        progs = []
        for path in paths:
            coms = path["env_infos"]["com"]
            progs.append(coms[-1][0] - coms[0][0])
                # x-coord of com at the last time step minus the 1st step

        n_directions = [
            np.max(progs) > self.prog_threshold,
            np.min(progs) < - self.prog_threshold,
        ].count(True)
        stats = {
            'env: ForwardProgressAverage': np.mean(progs),
            'env: ForwardProgressMax': np.max(progs),
            'env: ForwardProgressMin': np.min(progs),
            'env: ForwardProgressStd': np.std(progs),
            'env: ForwardProgressDiff': np.max(progs) - np.min(progs),
            'env: n_directions': n_directions,
        }
        # if self.visitation_plot_config is not None:
        #     self.plot_visitation(
        #         epoch,
        #         paths,
        #         mesh_density=self.visitation_plot_config["mesh_density"],
        #         prefix=self.visitation_plot_config["prefix"],
        #         variant=self.visitation_plot_config["variant"],
        #         save_to_file=True,
        #     )
        # snapshot_gap = logger.get_snapshot_gap()
        # if snapshot_gap <= 0 or \
        #     np.mod(epoch + 1, snapshot_gap) == 0 or \
        #     epoch == 0:
        #     snapshot_dir = logger.get_snapshot_dir()
        #     variant_file = os.path.join(
        #         snapshot_dir,
        #         "variant.json",
        #     )
        #     with open(variant_file) as vf:
        #         variant = json.load(vf)
        #     img_file = os.path.join(
        #         snapshot_dir,
        #         "itr_%d_test_paths.png"%(epoch),
        #     )
        #     self.plot_paths(algo, paths, variant, img_file)
        SwimmerUndirectedEnv.plot_paths(paths, ax)

        return stats

    @staticmethod
    def plot_paths(paths, ax):
        for path in paths:
            pos = path['env_infos']['com']
            xx = pos[:, 0]
            yy = pos[:, 1]
            ax.plot(xx, yy, 'b')
        xlim = np.ceil(np.max(np.abs(xx)))
        ax.set_xlim((-xlim, xlim))
        ax.set_ylim((-2, 2))

    def eval_qf(self, sess, qf, o, lim):
        xx = np.arange(-lim, lim, 0.05)
        X, Y = np.meshgrid(xx, xx)
        all_actions = np.vstack([X.ravel(), Y.ravel()]).transpose()
        obs = np.array([o] * all_actions.shape[0])

        feed = {
            qf.observations_placeholder: obs,
            qf.actions_placeholder: all_actions
        }
        Q = sess.run(qf.output, feed).reshape(X.shape)
        return X, Y, Q

    # def plot_paths(self, algo, paths, variant, img_file):
    #     # plot the test paths
    #     fig = plt.figure(figsize=(9, 14))
    #         # don't ask me how I figured out this ratio
    #     ax_paths = fig.add_subplot(211)
    #     ax_paths.grid(True)
    #     for path in paths:
    #         positions = path["env_infos"]["com"]
    #         xx = positions[:,0]
    #         yy = positions[:,1]
    #         ax_paths.plot(xx, yy, 'b')
    #     ax_paths.set_xlim((-4., 4.))
    #     ax_paths.set_ylim((-4., 4.))
    #
    #     # plot the q-value at the initial state
    #     ax_qf = fig.add_subplot(212)
    #     ax_qf.grid(True)
    #     lim = 1.
    #     ax_qf.set_xlim((-lim, lim))
    #     ax_qf.set_ylim((-lim, lim))
    #     obs = paths[0]["observations"][0]
    #         # assume the initial state is fixed
    #         # assume the observations are not normalized
    #     X, Y, Q = self.eval_qf(algo.sess, algo.qf, obs, lim)
    #     if hasattr(algo, "alpha"):
    #         alpha = algo.alpha
    #     else:
    #         alpha = 1
    #     log_prob = (Q - np.max(Q.ravel())) / alpha
    #     ax_qf.clear()
    #     cs = ax_qf.contour(X, Y, log_prob, 20)
    #     ax_qf.clabel(cs, inline=1, fontsize=10, fmt='%.2f')
    #
    #     # sample and plot actions
    #     if isinstance(algo.policy, StochasticNNPolicy):
    #         all_obs = np.array([obs] * algo.K)
    #         all_actions = algo.policy.get_actions(all_obs)[0]
    #     elif isinstance(algo.policy, MNNPolicy):
    #         all_actions, info = algo.policy.get_action(obs, k="all")
    #     elif isinstance(algo.policy, NNPolicy):
    #         all_actions, _ = algo.policy.get_action(obs)
    #     else:
    #         raise NotImplementedError
    #
    #     x = all_actions[:, 0]
    #     y = all_actions[:, 1]
    #     ax_qf.plot(x, y, '*')
    #
    #     # plot the action boundary, counterclockwise from the bottom left
    #     ax_qf.plot(
    #         [-1, 1, 1, -1, -1],
    #         [-1, -1, 1, 1, -1],
    #         'k-',
    #     )
    #
    #     # title contains the variant parameters
    #     fig_title = variant["exp_name"] + "\n"
    #     for key in sorted(variant.keys()):
    #         fig_title += "%s: %s \n"%(key, variant[key])
    #     ax_paths.set_title(fig_title, multialignment="left")
    #     fig.tight_layout()
    #
    #     plt.axis('equal')
    #     plt.draw()
    #     plt.pause(0.001)
    #
    #     # save to file
    #     plt.savefig(img_file, dpi=100)
    #     plt.cla()
    #     plt.close('all')
    #     gc.collect()
    #
    # def plot_visitation(self,
    #         epoch,
    #         paths,
    #         mesh_density=50,
    #         prefix='',
    #         save_to_file=False,
    #         fig=None,
    #         ax=None,
    #         variant=dict()
    #     ):
    #     """
    #     Specific to MDDPG.
    #     On a 2D grid centered at the origin, color the grid points that has been
    #     visited. A grid point is given color (j+1) if head number j (counting
    #     from 0) visits it most often. Color 0 (black) is reserved for unvisited
    #     points.
    #     """
    #     assert "agent_infos" in paths[0] and \
    #         "num_heads" in paths[0]["agent_infos"] and \
    #         "heads" in paths[0]["agent_infos"]
    #
    #     # count the number of times each head visits a grid point
    #     num_heads = paths[0]["agent_infos"]["num_heads"][0]
    #     counter = np.zeros((num_heads, mesh_density+1, mesh_density+1))
    #     all_com = np.concatenate(
    #         [path["env_infos"]["com"] for path in paths],
    #         axis=0
    #     )
    #     all_com_x = all_com[:,0]
    #     all_com_y = all_com[:,1]
    #     x_max = np.ceil(np.max(np.abs(all_com_x))) # boundaries must be ints?
    #     y_max = np.ceil(np.max(np.abs(all_com_y)))
    #     furthest = max(x_max, y_max)
    #     all_x_indices = np.floor(
    #         (all_com_x - (-furthest)) / (furthest - (-furthest)) * mesh_density
    #     ).astype(int)
    #     all_y_indices = np.floor(
    #         (all_com_y - (-furthest)) / (furthest - (-furthest)) * mesh_density
    #     ).astype(int)
    #     all_heads = np.concatenate(
    #         [path["agent_infos"]["heads"] for path in paths]
    #     )
    #     for k, ix, iy in zip(all_heads, all_x_indices, all_y_indices):
    #         counter[k,ix,iy] += 1
    #
    #     # compute colors
    #     delta = 2 * furthest /mesh_density
    #     Y,X = np.mgrid[-furthest:furthest+delta:delta, -furthest:furthest+delta:delta]
    #     visit_heads = np.argmax(counter, axis=0)
    #     has_visits = np.minimum(np.sum(counter, axis=0), 1)
    #     colors = (visit_heads + 1) * has_visits
    #
    #     # plot
    #     if fig is None or ax is None:
    #         fig, ax = plt.subplots()
    #     num_colors = num_heads + 1
    #     cmap = plt.get_cmap('nipy_spectral', num_colors)
    #     map_plot = ax.pcolormesh(X, Y, colors, cmap=cmap, vmin=0.1,
    #                              vmax=num_heads)
    #     color_len = (num_colors - 1.) / num_colors
    #     ticks = np.arange(color_len / 2., num_colors - 1, color_len)
    #     cbar = fig.colorbar(map_plot, ticks=ticks)
    #     latent_tick_labels = ['head %d'%(i) for i in range(num_heads)]
    #     cbar.ax.set_yticklabels(
    #         ['No visitation'] + latent_tick_labels + ['Repetitions'])
    #     ax.set_xlim([X[0][0], X[0][-1]])
    #     ax.set_ylim(Y[0][0],Y[-1][0])
    #
    #     # save the plot to a file if specified
    #     if save_to_file:
    #         snapshot_gap = logger.get_snapshot_gap()
    #         if snapshot_gap <= 0 or \
    #             np.mod(epoch + 1, snapshot_gap) == 0 or \
    #             epoch == 0:
    #             log_dir = logger.get_snapshot_dir()
    #             title = variant["exp_name"] + "\n" + \
    #                 "epoch: %d visit\n"%(epoch)
    #             for key, value in variant.items():
    #                 if key != "exp_name":
    #                     title += "%s: %s \n"%(key, value)
    #             ax.set_title(title, multialignment="left")
    #             fig.tight_layout()
    #
    #             plt.savefig(os.path.join(
    #                 log_dir,
    #                 prefix + 'visit_itr_%d.png'%(epoch),
    #             ))
    #             plt.close()
    #
    #             plt.cla()
    #             plt.clf()
    #             plt.close('all')
    #             gc.collect()