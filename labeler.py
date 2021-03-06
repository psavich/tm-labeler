import label_studio


def _train_model(self, data):
    c = self.c
    self._train_basics()  # prepare basic placeholders

    batch_size = data.batch_size
    self.X = tf.placeholder(tf.float32, shape=[batch_size, data.input_len, data.input_dim], name="X")
    self.Y = tf.placeholder(tf.float32, shape=[batch_size, data.output_len, data.output_dim], name="Y")

    layer = self.X

    # ... your model here ...

    # Output matmul
    units = c['model.units']
    weights = tf.Variable(tf.truncated_normal([units, data.output_dim], stddev=0.5))
    bias = tf.Variable(tf.constant(0.1, shape=[data.output_dim]))

    shape = tf.shape(layer)
    layer = tf.reshape(layer, [shape[0] * data.output_len, units])
    layer = tf.matmul(layer, weights) + bias  # [m, units] x [n, output_dim] = [m, output_dim]
    layer = tf.reshape(layer, [shape[0], data.output_len, data.output_dim])

    out = tf.identity(layer, name="output")
    self.out = out

    # cost & optimizer
    with tf.name_scope("cost_optimizer"):
        # loss function
        diff = tf.reduce_mean(tf.square(self.Y - out))
        self.cost = tf.clip_by_value(diff, 1e-40, 1e10)

        # optimizer
        self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate_tf).minimize(self.cost)


def train_step(self):
    # get data
    self.x, self.y = self.train_generator.get_values()

    # train step
    params = [self.cost, self.cost_summary, self.optimizer, self.out] + self.update_ops
    cost, cost_summary, _, self.train_prediction = self.sess.run(params, feed_dict={
        self.X: self.x,
        self.Y: self.y,

        self.training: 1,
        self.step_tf: self.step,
        self.epoch_tf: self.epoch,
        self.learning_rate_tf: self.learning_rate
    })

    self.train_writer.add_summary(cost_summary, global_step=self.epoch * self.data.steps_per_epoch + self.step)
    self.train_costs += [cost]


def validation_step(self):
    # get data
    self.test_x, self.test_y = self.valid_generator.get_values()

    # validate
    params = [self.cost, self.cost_summary, self.out] + self.update_ops
    cost, cost_summary, self.test_prediction = self.sess.run(params, feed_dict={
        self.X: self.test_x, self.Y: self.test_y})

    self.valid_writer.add_summary(cost_summary, global_step=self.epoch * self.data.validation_steps + self.valid_step)
    self.test_costs += [cost]


def _reset_history(self):
    self.history = {'loss': [], 'val_loss': [], 'loss_std': [], 'val_loss_std': [], 'time': [], 'lr': []}


def run_validation(self, write_history=True, run_callbacks=True):
    self.valid_step = 0
    self.test_costs = []
    [call.on_validation_begin() for call in self.callbacks if run_callbacks]

    while True:  # validation cycle
        [call.on_validation_step_begin() for call in self.callbacks if run_callbacks]
        self.validation_step()
        self.valid_writer.flush()  # write summary to disk right now
        [call.on_validation_step_end() for call in self.callbacks if run_callbacks]
        self.progress(self.step)
        self.valid_step += 1
        if self.valid_step >= self.data.validation_steps:
            break

    # print info to history
    if write_history:
        self.history['loss'] += [np.mean(self.train_costs)]
        self.history['loss_std'] += [np.std(self.train_costs)]
        self.history['val_loss'] += [np.mean(self.test_costs)]
        self.history['val_loss_std'] += [np.std(self.test_costs)]
        self.history['lr'] += [self.learning_rate]
        self.history['time'] += [time.time() - self.epoch_time_start]
        self.train_costs, self.test_costs = [], []

    [call.on_validation_end() for call in self.callbacks if run_callbacks]


def fit_data(self, data, callbacks=None, max_queue_size=100, thread_num=4, valid_thread_num=4,
             tensorboard_subdir=''):
    c = self.c
    # check deprecated function
    self.check_deprecated(c)

    self.set_data(data)
    self.epochs = c['model.epochs']
    self.callbacks = [] if callbacks is None else callbacks
    self.train_generator = threadgen.ThreadedGenerator(data, 'train', max_queue_size, thread_num).start()
    self.valid_generator = threadgen.ThreadedGenerator(data, 'valid', max_queue_size, valid_thread_num).start()
    self.keyboard = keyboard
    self.keyboard.start()

    # prepare train model
    device = c.get('model.tf.device', '')
    with tf.device(device):
        print(' Compiling model' + (' for device ' + device) if device else '')
        tf.reset_default_graph()
        tf.set_random_seed(1234)
        self._train_model(data)

    # session init & tf_debug
    if c.get('tf.session.target', ''):
        print('model tf session target:', c.get('tf.session.target', ''))
    self.sess = tf.Session(target=c.get('tf.session.target', ''), config=make_config_proto(c))
    if self.c.get('tf.debug.enabled', False):
        port = self.c.get('tf.debug.port', '6064')
        self.sess = tf_debug.TensorBoardDebugWrapperSession(self.sess, 'localhost:' + port)
    self.sess.run(tf.global_variables_initializer())

    # log writer & model saver
    self.tensorboard_subdir = os.path.join(self.tensorboard_root, tensorboard_subdir)
    with tf.summary.FileWriter(self.tensorboard_subdir + '/train') as self.train_writer, \
            tf.summary.FileWriter(self.tensorboard_subdir + '/valid') as self.valid_writer:

        self.train_writer.add_graph(self.sess.graph)
        if self.saver is None:
            self.saver = tf.train.Saver()

        # load weights if we want to continue training
        if 'model.preload' in c and c['model.preload']:
            self.load_weights(c['model.preload'], c.get('model.preload.verbose', False))

        # summary
        self.cost_summary = tf.summary.scalar("cost", self.cost)

        self._reset_history()
        self.epoch, self.step, train_cost, test_cost, restart = 1, 0, 0, 0, True
        self.epoch_time_start = time.time()
        self.train_costs, self.test_costs = [], []
        [call.set_model(self) for call in self.callbacks]  # set model to self.callbacks
        [call.set_config(c) for call in self.callbacks]  # set config to self.callbacks
        [call.on_start() for call in self.callbacks]  # self.callbacks
        print(' Train model')

        while self.epoch <= self.epochs:  # train cycle, we start from 1, so use <=
            ' epoch begin '
            if restart:
                restart = False
                self.step = 0
                self.info('\n  Epoch %i/%i\n' % (self.epoch, self.epochs))
                [call.on_epoch_begin() for call in self.callbacks]  # self.callbacks

            ' step begin '
            [call.on_step_begin() for call in self.callbacks]

            self.train_step()
            self.train_writer.flush()  # write summary to disk right now

            ' step end '
            [call.on_step_end() for call in self.callbacks]
            self.step += 1
            self.progress(self.step)  # print progress

            ' epoch end '
            if self.step >= self.data.steps_per_epoch or self.stop_training_now:

                ' validation pass '
                self.run_validation()

                # self.callbacks: on epoch end
                [call.on_epoch_end() for call in self.callbacks]
                sys.stdout.write('\n')

                # reset & stop check
                restart = True
                self.epoch += 1
                self.epoch_time_start = time.time()
                if self.stop_training or self.stop_training_now:
                    break  # break main loop

        self.train_generator.stop()
        self.valid_generator.stop()
        [call.on_finish() for call in self.callbacks]  # self.callbacks
        gc.collect()
        return self


def get_predictor(self, predictor_cls):
    if self.predictor is None:
        self.predictor = predictor_cls(self.c)
        self.predictor.prepare()
        self.predictor.set_session(self.sess)
    return self.predictor


def set_data(self, data):
    self.data = data


def set_config(self, config):
    self.c = config


def save(self, dir_path, saver=None):
    saver = self.saver if saver is None else saver
    os.makedirs(dir_path) if not os.path.exists(dir_path) else ()
    saver.save(self.sess, dir_path + '/model', global_step=self.epoch)
    json.dump(self.c, open(dir_path + '/config.json', 'w'), indent=4)


@classmethod
def load(cls, path, forced_config=None, *args, **kwargs):
    model = super(Model, cls).load(path, forced_config, *args, **kwargs)
    model._reset_history()
    return model


def load_weights(self, path, verbose=False):
    """ Load weights to current graph.
    It loads only variables with the same names and shapes from the checkpoint.

    :param path: path to model
    :param verbose: print debug info if True
    :return: None
    """
    if 'model.preload.verbose' in self.c:
        verbose = self.c['model.preload.verbose']

    if os.path.isdir(path):  # path is dir
        c = json.load(open(path + '/config.json'))
    else:  # path is filename
        c = json.load(open(os.path.dirname(path) + '/config.json'))

    model_name = ''
    if os.path.isdir(path):  # take the last model
        models = set([m.split('.')[0].split('-')[1] for m in os.listdir(path) if 'model-' in m])  # get all models
        model_number = sorted([int(m) for m in models])[-1]  # last item
        model_name = '/model-%i' % model_number

    # get variables from _train_model (current graph)
    current_vars = current_vars_all = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)

    # exclude variables using config exclude_var_names
    if 'model.preload.exclude_var_names' in self.c:
        new = []
        exclude_names = self.c['model.preload.exclude_var_names']
        if not isinstance(exclude_names, list):
            raise Exception('model.preload.exclude_var_names must be list of strings')

        for v in current_vars_all:
            exclude = [True for substr in exclude_names if substr in v.name]
            if not exclude:
                new += [v]
        current_vars = new

    # get variable names from checkpoint
    reader = pywrap_tensorflow.NewCheckpointReader(path + model_name)
    loading_shapes = reader.get_variable_to_shape_map()
    loading_names = sorted(reader.get_variable_to_shape_map())

    # find intersect of loading and current variables
    intersect_vars = []
    ignored_names = []
    for n in loading_names:
        included = False
        # add var
        for v in current_vars:
            if n == v.name.split(':')[0] and v.shape == loading_shapes[n]:
                intersect_vars += [v]
                included = True
        # ignore var
        if not included:
            ignored_names += [n]

    # print intersection
    if verbose:
        if 'model.preload.exclude_var_names' in self.c:
            print('\nExcluded variables:')
            print(self.c['model.preload.exclude_var_names'])

        print('\nVariables from current model - exclude_var_names (from config):')
        for i in sorted([v.name for v in current_vars]):
            print(' ', i)

        print('\nVariables from loading model:')
        for key in loading_names:
            print(' ', key)

        print('\nIntersect variables:')
        for v in intersect_vars:
            print(' ', v.name)

        print('\nIgnored variables:')
        for n in ignored_names:
            print(' ', n)
        print()
    label_studio.server.start()
    saver = tf.train.Saver(var_list=intersect_vars)
    saver.restore(self.sess, path + model_name)
    print(' ', str(len(intersect_vars)) + '/' + str(len(current_vars_all)), 'variables loaded', path + model_name,
          '\n')

    return

