import numpy as np
# from sandbox.rein.dynamics_models.bnn.conv_bnn import ConvBNN
import lasagne
from sandbox.rein.dynamics_models.utils import iterate_minibatches, plot_mnist_digit, load_dataset_MNIST, \
    load_dataset_MNIST_plus, load_dataset_Atari_plus
from sandbox.rein.dynamics_models.bnn.conv_bnn_vime import ConvBNNVIME
import time
import rllab.misc.logger as logger


# import theano
# theano.config.exception_verbosity='high'

class Experiment(object):
    def plot_pred_imgs(self, model, inputs, targets, itr, count):
        # This is specific to Atari.
        import matplotlib.pyplot as plt
        if not hasattr(self, '_fig'):
            self._fig = plt.figure()
            self._fig_1 = self._fig.add_subplot(141)
            plt.tick_params(axis='both', which='both', bottom='off', top='off',
                            labelbottom='off', right='off', left='off', labelleft='off')
            self._fig_2 = self._fig.add_subplot(142)
            plt.tick_params(axis='both', which='both', bottom='off', top='off',
                            labelbottom='off', right='off', left='off', labelleft='off')
            self._fig_3 = self._fig.add_subplot(143)
            plt.tick_params(axis='both', which='both', bottom='off', top='off',
                            labelbottom='off', right='off', left='off', labelleft='off')
            self._fig_4 = self._fig.add_subplot(144)
            plt.tick_params(axis='both', which='both', bottom='off', top='off',
                            labelbottom='off', right='off', left='off', labelleft='off')
            self._im1, self._im2, self._im3, self._im4 = None, None, None, None

        idx = np.random.randint(0, inputs.shape[0], 1)
        sanity_pred = model.pred_fn(inputs)
        input_im = inputs
        input_im = input_im[idx, :].reshape((1, 84, 84)).transpose(1, 2, 0)[:, :, 0]
        sanity_pred_im = sanity_pred[idx, :-1]
        sanity_pred_im = sanity_pred_im.reshape((-1, model.num_classes))
        sanity_pred_im = np.argmax(sanity_pred_im, axis=1)
        sanity_pred_im = sanity_pred_im.reshape((1, 84, 84)).transpose(1, 2, 0)[:, :, 0]
        target_im = targets[idx, :].reshape((1, 84, 84)).transpose(1, 2, 0)[:, :, 0]

        sanity_pred_im = sanity_pred_im.astype(float) / float(model.num_classes)
        target_im = target_im.astype(float) / float(model.num_classes)
        input_im = input_im.astype(float) / float(model.num_classes)
        err = np.abs(target_im - sanity_pred_im)

        if self._im1 is None or self._im2 is None:
            self._im1 = self._fig_1.imshow(
                input_im, interpolation='none', cmap='Greys_r', vmin=0, vmax=1)
            self._im2 = self._fig_2.imshow(
                target_im, interpolation='none', cmap='Greys_r', vmin=0, vmax=1)
            self._im3 = self._fig_3.imshow(
                sanity_pred_im, interpolation='none', cmap='Greys_r', vmin=0, vmax=1)
            self._im4 = self._fig_4.imshow(
                err, interpolation='none', cmap='Greys_r', vmin=0, vmax=1)
        else:
            self._im1.set_data(input_im)
            self._im2.set_data(target_im)
            self._im3.set_data(sanity_pred_im)
            self._im4.set_data(err)
        plt.savefig(
            logger._snapshot_dir + '/dynpred_img_{}_{}.png'.format(itr, count), bbox_inches='tight')

    def train(self, model, num_epochs=500, X_train=None, T_train=None, X_test=None, T_test=None, plt=None, act=None,
              rew=None,
              im=None, ind_softmax=False):

        im_size = X_train.shape[-1]
        X_train = X_train.reshape(-1, im_size * im_size)
        T_train = T_train.reshape(-1, im_size * im_size)
        X = np.hstack((X_train, act))
        Y = np.hstack((T_train, rew))

        logger.log('Training ...')

        for epoch in range(num_epochs):

            # In each epoch, we do a full pass over the training data:
            train_err, train_batches, start_time, kl_values = 0, 0, time.time(), []

            if not model.disable_variance:
                print('KL[post||prior]: {}'.format(model.log_p_w_q_w_kl().eval()))

            # Iterate over all minibatches and train on each of them.
            for batch in iterate_minibatches(X, Y, model.batch_size, shuffle=True):
                # Fix old params for KL divergence computation.
                model.save_params()

                # Train current minibatch.
                inputs, targets, _ = batch

                _train_err = model.train_fn(inputs, targets, 1.0)

                train_err += _train_err
                train_batches += 1

            pred = model.pred_fn(X)
            pred_im = pred[:, :-1]
            if ind_softmax:
                pred_im = pred_im.reshape((-1, im_size * im_size, model.num_classes))
                pred_im = np.argmax(pred_im, axis=2)

            acc = np.mean(np.sum(np.square(pred_im - Y[:, :-1]), axis=1), axis=0)

            self.plot_pred_imgs(model, X_train, T_train, epoch, 1)

            logger.record_tabular('train loss', train_err / float(train_batches))
            logger.record_tabular('obs err', acc)
            logger.log("Epoch {} of {} took {:.3f}s".format(
                epoch + 1, num_epochs, time.time() - start_time))

            logger.dump_tabular(with_prefix=False)

        logger.log("Done training.")

    def bin_img(self, lst_img, num_bins):
        for img in lst_img:
            img *= num_bins

    def main(self):
        num_epochs = 10000
        batch_size = 8
        IND_SOFTMAX = True
        NUM_BINS = 30
        PRED_DELTA = False

        print("Loading data ...")
        # X_train, T_train, act, rew = load_dataset_MNIST_plus()
        X_train, T_train, act, rew = load_dataset_Atari_plus()
        X_train1 = np.vstack([X_train[1] for i in xrange(50)])
        T_train1 = np.vstack([T_train[1] for i in xrange(50)])
        X_train0 = np.vstack([X_train[0] for i in xrange(50)])
        T_train0 = np.vstack([T_train[0] for i in xrange(50)])

        X_train = np.vstack((X_train0, X_train1))
        T_train = np.vstack((T_train0, T_train1))

        X_train = X_train[:, np.newaxis, :, :]
        T_train = T_train[:, np.newaxis, :, :]
        if IND_SOFTMAX:
            self.bin_img(X_train, NUM_BINS)
            self.bin_img(T_train, NUM_BINS)
            X_train = X_train.astype(int)
            T_train = T_train.astype(int)
        elif PRED_DELTA:
            T_train = X_train - T_train

        n_batches = int(np.ceil(len(X_train) / float(batch_size))) * 1000

        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.figure()
        # im = plt.imshow(
        #     T_train[0, 0, :, :], cmap='gist_gray_r', vmin=0, vmax=1,
        #     interpolation='none')

        print("Building model and compiling functions ...")
        bnn = ConvBNNVIME(
            # state_dim=(1, 28, 28),
            # action_dim=(2,),
            # reward_dim=(1,),
            # layers_disc=[
            #     dict(name='convolution',
            #          n_filters=2,
            #          filter_size=(4, 4),
            #          stride=(2, 2),
            #          pad=(0, 0)),
            #     dict(name='reshape',
            #          shape=([0], -1)),
            #     dict(name='gaussian',
            #          n_units=338,
            #          matrix_variate_gaussian=True),
            #     dict(name='gaussian',
            #          n_units=128,
            #          matrix_variate_gaussian=True),
            #     dict(name='hadamard',
            #          n_units=128,
            #          matrix_variate_gaussian=True),
            #     dict(name='gaussian',
            #          n_units=338,
            #          matrix_variate_gaussian=True),
            #     dict(name='split',
            #          n_units=128,
            #          matrix_variate_gaussian=True),
            #     dict(name='reshape',
            #          shape=([0], 2, 13, 13)),
            #     dict(name='deconvolution',
            #          n_filters=1,
            #          filter_size=(4, 4),
            #          stride=(2, 2),
            #          pad=(0, 0),
            #          nonlinearity=lasagne.nonlinearities.linear)
            # ],
            state_dim=(1, 84, 84),
            action_dim=(2,),
            reward_dim=(1,),
            layers_disc=[
                dict(name='convolution',
                     n_filters=16,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(0, 0)),
                dict(name='convolution',
                     n_filters=16,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(2, 2)),
                dict(name='convolution',
                     n_filters=16,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(2, 2)),
                dict(name='reshape',
                     shape=([0], -1)),
                dict(name='gaussian',
                     n_units=2048,
                     matrix_variate_gaussian=False),
                dict(name='gaussian',
                     n_units=2048,
                     matrix_variate_gaussian=False),
                dict(name='hadamard',
                     n_units=2048,
                     matrix_variate_gaussian=False),
                dict(name='gaussian',
                     n_units=2048,
                     matrix_variate_gaussian=False),
                dict(name='split',
                     n_units=2048,
                     matrix_variate_gaussian=False),
                dict(name='gaussian',
                     n_units=1600,
                     matrix_variate_gaussian=False),
                dict(name='reshape',
                     shape=([0], 16, 10, 10)),
                dict(name='deconvolution',
                     n_filters=16,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(2, 2),
                     nonlinearity=lasagne.nonlinearities.rectify),
                dict(name='deconvolution',
                     n_filters=16,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(2, 2),
                     nonlinearity=lasagne.nonlinearities.rectify),
                dict(name='deconvolution',
                     n_filters=1,
                     filter_size=(6, 6),
                     stride=(2, 2),
                     pad=(0, 0),
                     nonlinearity=lasagne.nonlinearities.linear),
            ],
            n_batches=n_batches,
            batch_size=batch_size,
            n_samples=1,
            num_train_samples=1,
            prior_sd=0.05,
            update_likelihood_sd=False,
            learning_rate=0.00001,
            group_variance_by=ConvBNNVIME.GroupVarianceBy.UNIT,
            use_local_reparametrization_trick=False,
            likelihood_sd_init=0.1,
            output_type=ConvBNNVIME.OutputType.REGRESSION,
            surprise_type=ConvBNNVIME.SurpriseType.COMPR,
            disable_variance=True,
            second_order_update=False,
            debug=True,
            # ---
            ind_softmax=IND_SOFTMAX,
            num_classes=NUM_BINS
        )

        # Train the model.
        self.train(bnn, num_epochs=num_epochs, X_train=X_train, T_train=T_train, act=act, rew=rew, im=None,
                   ind_softmax=IND_SOFTMAX)
        print('Done.')
