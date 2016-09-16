# from rllab.algos.trpo import TRPO
# from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.envs.box2d.cartpole_env import CartpoleEnv
from rllab.envs.normalized_env import normalize
# from rllab.misc.instrument import stub, run_experiment_lite
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy

from sandbox.adam.parallel.trpo import ParallelTRPO
from sandbox.adam.parallel.linear_feature_baseline import ParallelLinearFeatureBaseline

# stub(globals())

env = normalize(CartpoleEnv())

policy = GaussianMLPPolicy(
    env_spec=env.spec,
    # The neural network policy should have two hidden layers, each with 32 hidden units.
    hidden_sizes=(32, 32)
)

baseline = ParallelLinearFeatureBaseline(env_spec=env.spec)

algo = ParallelTRPO(
    env=env,
    policy=policy,
    baseline=baseline,
    batch_size=4000,
    max_path_length=100,
    n_itr=5,
    discount=0.99,
    step_size=0.01,
    n_parallel=2,
    # Uncomment both lines (this and the plot parameter below) to enable plotting
    # plot=True,
)

algo.train()

# run_experiment_lite(
#     algo.train(),
#     # Number of parallel workers for sampling
#     n_parallel=1,
#     # Only keep the snapshot parameters for the last iteration
#     snapshot_mode="last",
#     # Specifies the seed for the experiment. If this is not provided, a random seed
#     # will be used
#     seed=1,
#     # plot=True,
# )
