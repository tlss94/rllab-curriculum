from __future__ import print_function
from __future__ import absolute_import

info = """Running more sparse tasks with Hashing Bonus Reward (no mujoco)"""

from rllab.misc.instrument import stub, run_experiment_lite
from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.envs.normalized_env import normalize
from sandbox.rocky.hashing.algos.bonus_trpo import BonusTRPO
from sandbox.rocky.hashing.bonus_evaluators.hashing_bonus_evaluator import HashingBonusEvaluator
from sandbox.rein.envs.cartpole_swingup_env_x import CartpoleSwingupEnvX
from sandbox.rein.envs.double_pendulum_env_x import DoublePendulumEnvX
from sandbox.rocky.tf.policies.gaussian_mlp_policy import GaussianMLPPolicy
from sandbox.rocky.tf.envs.base import TfEnv

import sys
import argparse

stub(globals())

from rllab.misc.instrument import VariantGenerator

N_ITR = 200
N_ITR_DEBUG = 5

envs = [CartpoleSwingupEnvX(),
        DoublePendulumEnvX()]


def experiment_variant_generator():
    vg = VariantGenerator()
    vg.add("env", map(TfEnv, map(normalize, envs)))
    vg.add("batch_size", [4000], hide=True)
    vg.add("step_size", [0.01], hide=True)
    vg.add("max_path_length", [100], hide=True)
    vg.add("discount", [0.99], hide=True)
    vg.add("seed", range(5), hide=True)
    vg.add("bonus_coeff", [0, 0.001, 0.01, 0.1, 1])
    vg.add("bonus_evaluator", lambda env: [HashingBonusEvaluator(env.spec)], hide=True)
    vg.add("baseline",
           lambda env: [LinearFeatureBaseline(env.spec)],
           hide=True
           )
    return vg


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--local",
                        help="run experiment locally",
                        action="store_true")
    parser.add_argument("-v", "--visualize",
                        help="visualize simulations during experiment",
                        action="store_true")
    parser.add_argument("-d", "--debug",
                        help="run in debug mode (only one configuration; don't terminate machines)",
                        action="store_true")
    parser.add_argument("-i", "--info",
                        help="display experiment info (without running experiment)",
                        action="store_true")
    parser.add_argument("-n", "--n-itr", type=int,
                        help="number of iterations (overrides default; mainly for debugging)")
    args = parser.parse_args()
    if args.info:
        print(info.replace('\n', ' '))
        sys.exit(0)
    return args

if __name__ == '__main__':
    args = parse_args()
    exp_prefix = __file__.split('/')[-1][:-3].replace('_', '-')
    if args.debug:
        exp_prefix += '-DEBUG'
    N_ITR = args.n_itr if args.n_itr is not None else N_ITR_DEBUG if args.debug else N_ITR
    vg = experiment_variant_generator()
    variants = vg.variants()
    print("Running experiment {}.".format(exp_prefix))
    print("Number of experiments to run: {}.".format(len(variants) if not args.debug else 1))
    for variant in variants:
        exp_name = vg.to_name_suffix(variant)
        if exp_name == '':
            exp_name = None

        policy = GaussianMLPPolicy(
            name="policy",
            env_spec=variant["env"].spec,
        )

        algo = BonusTRPO(
            bonus_evaluator=variant["bonus_evaluator"],
            bonus_coeff=variant["bonus_coeff"],
            env=variant["env"],
            policy=policy,
            baseline=variant["baseline"],
            batch_size=variant["batch_size"],
            whole_paths=True,
            max_path_length=variant["max_path_length"],
            n_itr=N_ITR,
            discount=variant["discount"],
            step_size=variant["step_size"],
            plot=args.visualize and args.local,
        )

        run_experiment_lite(
            algo.train(),
            n_parallel=1,
            snapshot_mode="last",
            seed=variant["seed"],
            plot=args.visualize and args.local,
            mode="local" if args.local else "ec2",
            exp_prefix=exp_prefix,
            terminate_machine=not args.debug
        )

        if args.debug:
            break  # Only run first experiment variant in debug mode