import numpy as np
import tensorflow as tf

from sandbox.haoran.mddpg.core.tf_util import he_uniform_initializer, \
    mlp, linear, weight_variable
from rllab.core.serializable import Serializable
from sandbox.haoran.mddpg.policies.nn_policy import NNPolicy

class MNNPolicy(NNPolicy):
    """ Multi-headed Neural Network Policy """
    def __init__(
        self,
        scope_name,
        observation_dim,
        action_dim,
        K,
        randomized=False,
        **kwargs
    ):
        """
        :param randomized: use this if you want the policy to always
            randomly switch a head at each time step, except if it
            is told to use a head explicitly. This is used in conjunction
            with MNNStrategy.switch_type = "per_action"
        """
        Serializable.quick_init(self, locals())
        self.K = K
        self.k = np.random.randint(0,K)
        self.randomized = randomized
        super(MNNPolicy, self).__init__(
            scope_name, observation_dim, action_dim)

    def create_network(self):
        with tf.variable_scope(self.scope_name):
            with tf.variable_scope('shared'):
                self.shared_variables = self.create_shared_variables()
            self.heads = []
            self.pre_heads = []
            for k in range(self.K):
                with tf.variable_scope('head_%d'%(k)):
                    output, pre_output = self.create_head(k)
                    self.heads.append(output)
                    self.pre_heads.append(pre_output)
            self.pre_output = tf.pack(self.pre_heads, axis=1, name='pre_outputs')

            return tf.pack(self.heads, axis=1, name='outputs')

    def create_head(self, k):
        raise NotImplementedError

    def create_shared_variables(self):
        raise NotImplementedError

    def get_action(self, observation, k=None):
        """
        k: which head to use
        By default, the policy decides which head to use. This is compatible
            with rllab.sampler.utils.rollout(), needed for evaluation.
        k = "all" returns all heads' actions.
        An exploration strategy may overwrite this method and specify particular
            heads.
        """
        if self.randomized:
            k = np.random.randint(low=0, high=self.K)
        if k is None:
            k = self.k
            return self.sess.run(
                self.heads[k],
                {self.observations_placeholder: [observation]}
            ), {
                'heads': k,
                'num_heads': self.K,
            }
        elif k == "all":
            return self.sess.run(
                self.output,
                {self.observations_placeholder: [observation]}
            ), {
                'heads':-1,
                'num_heads': self.K,
            }
        elif (isinstance(k, int) or isinstance(k,np.int64)) and 0 <= k <= self.K:
            return self.sess.run(
                self.heads[k],
                {self.observations_placeholder: [observation]}
            ), {
                'heads': k,
                'num_heads': self.K,
            }
        else:
            raise NotImplementedError



    def get_actions(self, observations):
        """
        By default, returns all candidate actions, since this method is probably
        only used when updating Q and pi.
        """
        return self.sess.run(
            self.output,
            {self.observations_placeholder: observations}
        ), {'heads': -np.ones(len(observations))}

    def reset(self):
        """
        Should use MNNStrategy to switch heads during training.
        Warning: "pass" will make rllab.samplers.utils.rollout() unable to
        switch heads between rollouts, which will make BatchSampler fail to
        sample paths for different heads.
        """
        pass


from rllab.exploration_strategies.base import ExplorationStrategy
class MNNStrategy(ExplorationStrategy):
    """
    Cleverly chooses between heads to do exploration.
    The current version switches a head after finishing a traj.
    """
    def __init__(self, K, substrategy, switch_type):
        self.K = K
        self.substrategy = substrategy
        self.switch_type = switch_type

        assert self.switch_type in ["per_action", "per_path"]

        self.k = 0 # current head

    def get_action(self, t, observation, policy, **kwargs):
        assert isinstance(policy, MNNPolicy)
        action, _ = policy.get_action(observation, self.k)
        action_modified = self.substrategy.get_modified_action(t, action)
        if self.switch_type == "per_action":
            self.k = np.random.randint(low=0, high=self.K)
            # print("{} switches to head {}".format(policy.scope_name, self.k))
        return action_modified

    def reset(self):
        if self.switch_type == "per_path":
            self.k = np.random.randint(low=0, high=self.K)
        self.substrategy.reset()

class FeedForwardMultiPolicy(MNNPolicy):
    def __init__(
        self,
        scope_name,
        observation_dim,
        action_dim,
        K,
        shared_hidden_sizes=(100, 100),
        independent_hidden_sizes=tuple(),
        hidden_W_init=None,
        hidden_b_init=None,
        output_W_init=None,
        output_b_init=None,
        hidden_nonlinearity=tf.nn.relu,
        output_nonlinearity=tf.nn.tanh,
        **kwargs
    ):
        Serializable.quick_init(self, locals())
        self.shared_hidden_sizes = shared_hidden_sizes
        self.independent_hidden_sizes = independent_hidden_sizes
        self.hidden_W_init = hidden_W_init or he_uniform_initializer()
        self.hidden_b_init = hidden_b_init or tf.constant_initializer(0.)
        self.output_W_init = output_W_init or tf.random_uniform_initializer(
            -3e-3, 3e-3)
        self.output_b_init = output_b_init or tf.random_uniform_initializer(
            -3e-3, 3e-3)
        self.hidden_nonlinearity = hidden_nonlinearity
        self.output_nonlinearity = output_nonlinearity
        super(FeedForwardMultiPolicy, self).__init__(
            scope_name,
            observation_dim,
            action_dim,
            K,
            **kwargs
        )
    def create_shared_variables(self):
        shared_layer = mlp(
            self.observations_placeholder,
            self.observation_dim,
            self.shared_hidden_sizes,
            self.hidden_nonlinearity,
            W_initializer=self.hidden_W_init,
            b_initializer=self.hidden_b_init,
        )
        return {"shared_layer": shared_layer}

    def create_head(self,k):
        if len(self.shared_hidden_sizes) > 0:
            shared_output_size = self.shared_hidden_sizes[-1]
        else:
            shared_output_size = self.observation_dim

        # TH: Hacky way to initialize different heads with different consts.
        if type(self.output_b_init) == list:
            output_b_initializer = tf.constant_initializer(
                self.output_b_init[k]
            )
        else:
            output_b_initializer = self.output_b_init

        pre_output_layer = mlp(
            self.shared_variables["shared_layer"],
            shared_output_size,
            self.independent_hidden_sizes,
            self.hidden_nonlinearity,
            W_initializer=self.hidden_W_init,
            b_initializer=self.hidden_b_init,
        )
        if len(self.independent_hidden_sizes) > 0:
            pre_output_layer_size = self.independent_hidden_sizes[-1]
        elif len(self.shared_hidden_sizes) > 0:
            pre_output_layer_size = self.shared_hidden_sizes[-1]
        else:
            pre_output_layer_size = self.observation_dim
        pre_output = linear(
            pre_output_layer,
            pre_output_layer_size,
            self.action_dim,
            W_initializer=self.output_W_init,
            b_initializer=output_b_initializer,
            #b_initializer=self.output_b_init,
        )
        output = self.output_nonlinearity(pre_output)
        return output, pre_output