from __future__ import print_function
from __future__ import absolute_import

import tensorflow as tf

c = tf.constant("Hello, distributed TensorFlow!")
server = tf.train.Server.create_local_server()
sess = tf.Session(server.target)
print(sess.run(c))
