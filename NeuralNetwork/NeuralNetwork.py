# encoding: utf8

import os
import cv2
import time
import pickle
import platform
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import matplotlib.cm as cm

from config import *
from Layers import *
from Util import ProgressBar, Timing, get_line_info

np.random.seed(142857)  # for reproducibility

""" To do: verbose """


# Neural Network

class NN:

    NNTiming = Timing()

    def __init__(self):
        self._layers, self._weights, self._bias = [], [], []
        self._layer_names, self._layer_shapes, self._layer_params = [], [], []
        self._lr, self._epoch, self._regularization_param = 0, 0, 0
        self._optimizer, self._optimizer_name, self._optimizer_params = None, "", []
        self._data_size = 0

        self._whether_apply_bias = False
        self._current_dimension = 0
        self._cost_layer = "Undefined"

        self._logs = []
        self._timings = {}
        self._metrics, self._metric_names = [], []

        self._x, self._y = None, None
        self._x_min, self._x_max = 0, 0
        self._y_min, self._y_max = 0, 0

        # Sets & Dictionaries

        self._available_metrics = {
            "acc": NN._acc, "_acc": NN._acc,
            "f1": NN._f1_score, "_f1_score": NN._f1_score
        }
        self._available_root_layers = {
            "Tanh": Tanh, "Sigmoid": Sigmoid,
            "ELU": ELU, "ReLU": ReLU, "Softplus": Softplus,
            "Softmax": Softmax,
            "Identical": Identical
        }
        self._available_sub_layers = {
            "Dropout", "MSE", "Cross Entropy", "Log Likelihood"
        }
        self._available_cost_functions = {
            "MSE", "Cross Entropy", "Log Likelihood"
        }
        self._available_special_layers = {
            "Dropout": Dropout
        }
        self._available_optimizers = {
            "SGD": self._sgd,
            "NAG": self._nag,
            "Adam": self._adam,
            "Momentum": self._momentum,
            "RMSProp": self._rmsprop,
            "CF0910": self._cf0910,
        }
        self._special_layer_default_params = {
            "Dropout": 0.5
        }

    def initialize(self):
        self._layers, self._weights, self._bias = [], [], []
        self._layer_names, self._layer_shapes, self._layer_params = [], [], []
        self._lr, self._epoch, self._regularization_param = 0, 0, 0
        self._optimizer, self._optimizer_name, self._optimizer_params = None, "", []
        self._data_size = 0

        self._whether_apply_bias = False
        self._current_dimension = 0
        self._cost_layer = "Undefined"

        self._logs = []
        self._timings = {}
        self._metrics, self._metric_names = [], []

        self._x, self._y = None, None
        self._x_min, self._x_max = 0, 0
        self._y_min, self._y_max = 0, 0

    def feed_timing(self, timing):
        if isinstance(timing, Timing):
            self.NNTiming = timing
            for layer in self._layers:
                layer.feed_timing(timing)

    def __str__(self):
        return "Neural Network"

    __repr__ = __str__

    # Property

    @property
    def name(self):
        return (
            "-".join([str(_layer.shape[1]) for _layer in self._layers]) +
            " at {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        )

    @property
    def layer_names(self):
        return [layer.name for layer in self._layers]

    @layer_names.setter
    def layer_names(self, value):
        self._layer_names = value

    @property
    def layer_shapes(self):
        return [layer.shape for layer in self._layers]

    @layer_shapes.setter
    def layer_shapes(self, value):
        self._layer_shapes = value

    @property
    def layer_params(self):
        return self._layer_params

    @layer_params.setter
    def layer_params(self, value):
        self.layer_params = value

    @property
    def optimizer(self):
        return self._optimizer_name

    @optimizer.setter
    def optimizer(self, value):
        try:
            self._optimizer, self._optimizer_name = self._available_optimizers[value], value
        except KeyError:
            raise BuildNetworkError("Invalid Optimizer '{}' provided".format(value))

    # Utils

    def __getitem__(self, item):
        if isinstance(item, int):
            if item < 0 or item >= len(self._layers):
                return
            bias = self._bias[item]
            return {
                "name": self._layers[item].name,
                "weight": self._weights[item],
                "bias": bias
            }
        if isinstance(item, str):
            return getattr(self, "_" + item)
        return

    @NNTiming.timeit(level=4)
    def _feed_data(self, x, y):
        if x is None:
            if self._x is None:
                raise BuildNetworkError("Please provide input matrix")
            x = self._x
        if y is None:
            if self._y is None:
                raise BuildNetworkError("Please provide input matrix")
            y = self._y
        if len(x) != len(y):
            raise BuildNetworkError("Data fed to network should be identical in length, x: {} and y: {} found".format(
                len(x), len(y)
            ))
        self._x, self._y = x, y
        self._x_min, self._x_max = np.min(x), np.max(x)
        self._y_min, self._y_max = np.min(y), np.max(y)
        self._data_size = len(x)
        return x, y

    @NNTiming.timeit(level=4)
    def _add_weight(self, shape):
        self._weights.append(2 * np.random.random(shape) - 1)
        self._bias.append(np.zeros((1, shape[1])))

    @NNTiming.timeit(level=4)
    def _add_layer(self, layer, *args):
        _parent = self._layers[-1]
        special_param = None
        if isinstance(_parent, CostLayer):
            raise BuildLayerError("Adding layer after CostLayer is not permitted")
        if isinstance(layer, str):
            if layer not in self._available_sub_layers:
                raise BuildLayerError("Invalid SubLayer '{}' provided".format(layer))
            _current, _next = _parent.shape[1], self._current_dimension
            if layer in self._available_cost_functions:
                layer = CostLayer((_current, _next), _parent, layer)
            else:
                if args:
                    if layer == "Dropout":
                        try:
                            prob = float(args[0])
                            special_param = prob
                            layer = Dropout((_current, _next), _parent, prob)
                        except ValueError as err:
                            raise BuildLayerError("Invalid parameter for Dropout: '{}'".format(err))
                        except BuildLayerError as err:
                            raise BuildLayerError("Invalid parameter for Dropout: {}".format(err))
                else:
                    special_param = self._special_layer_default_params[layer]
                    layer = self._available_special_layers[layer]((_current, _next), _parent)
        else:
            _current, _next = args
        if isinstance(layer, SubLayer):
            if not isinstance(layer, CostLayer) and _current != _parent.shape[1]:
                raise BuildLayerError("Output shape should be identical with input shape "
                                      "if chosen SubLayer is not a CostLayer")
            _parent.child = layer
            layer.root = layer.root
            layer.root.last_sub_layer = layer
            if isinstance(layer, CostLayer):
                layer.root.is_last_root = True
            self.parent = _parent
            self._layers.append(layer)
            self._weights.append(np.eye(_current))
            self._bias.append(np.zeros((1, _current)))
            self._current_dimension = _next
        else:
            self._layers.append(layer)
            self._add_weight((_current, _next))
            self._current_dimension = _next
        self._update_layer_information(special_param)

    @NNTiming.timeit(level=4)
    def _add_cost_layer(self):
        _last_layer = self._layers[-1]
        _last_layer_root = _last_layer.root
        if not isinstance(_last_layer, CostLayer):
            if _last_layer_root.name == "Sigmoid":
                self._cost_layer = "Cross Entropy"
            elif _last_layer_root.name == "Softmax":
                self._cost_layer = "Log Likelihood"
            else:
                self._cost_layer = "MSE"
            self.add(self._cost_layer)

    @NNTiming.timeit(level=4)
    def _update_layer_information(self, *args):
        if len(args) == 1:
            self._layer_params.append(*args)
        else:
            self._layer_params.append(args)

    @NNTiming.timeit(level=4)
    def _get_accuracy(self, x, y):
        y_pred = self._get_prediction(x)
        return NN._acc(y, y_pred)

    @NNTiming.timeit(level=1)
    def _get_prediction(self, x):
        return self._get_activations(x, predict=True).pop()

    @NNTiming.timeit(level=1)
    def _get_activations(self, x, predict=False):
        _activations = [self._layers[0].activate(x, self._weights[0], self._bias[0], predict)]
        for i, layer in enumerate(self._layers[1:]):
            _activations.append(layer.activate(
                _activations[-1], self._weights[i + 1], self._bias[i + 1], predict))
        return _activations

    @NNTiming.timeit(level=3)
    def _append_log(self, x, y, get_loss=True):
        y_pred = self._get_prediction(x)
        for i, metric in enumerate(self._metrics):
            self._logs[i].append(metric(y, y_pred))
        if get_loss:
            self._logs[-1].append(self._layers[-1].calculate(y, self.predict(x)) / self._data_size)

    @NNTiming.timeit(level=3)
    def _print_metric_logs(self, x, y, show_loss):
        print()
        print("-" * 30)
        for i, name in enumerate(self._metric_names):
            print("{:<16s}: {:12.8}".format(name, self._logs[i][-1]))
        if show_loss:
            print("{:<16s}: {:12.8}".format("loss", self._layers[-1].calculate(y, self.predict(x)) / self._data_size))
        print("-" * 30)

    # Metrics

    @staticmethod
    @NNTiming.timeit(level=2, prefix="[Private StaticMethod] ")
    def _acc(y, y_pred):
        y_arg, y_pred_arg = np.argmax(y, axis=1), np.argmax(y_pred, axis=1)
        return np.sum(y_arg == y_pred_arg) / len(y_arg)

    @staticmethod
    @NNTiming.timeit(level=2, prefix="[Private StaticMethod] ")
    def _f1_score(y, y_pred):
        y_true, y_pred = np.argmax(y, axis=1), np.argmax(y_pred, axis=1)
        tp = np.sum(y_true * y_pred)
        if tp == 0:
            return .0
        fp = np.sum((1 - y_true) * y_pred)
        fn = np.sum(y_true * (1 - y_pred))
        return 2 * tp / (2 * tp + fn + fp)

    # Optimizers

    @NNTiming.timeit(level=4)
    def _init_optimizer(self):
        name = self._optimizer_name
        if name == "SGD":
            return
        if name == "NAG":
            self._optimizer_params = [
                [np.zeros(weight.shape) for weight in self._weights],
                [np.zeros(bias.shape) for bias in self._bias],
                0.5, 0.499 / self._epoch, 0
            ]
        elif name == "Adam":
            self._optimizer_params = [
                [np.zeros(weight.shape) for weight in self._weights],
                [np.zeros(weight.shape) for weight in self._weights],
                [np.zeros(bias.shape) for bias in self._bias],
                [np.zeros(bias.shape) for bias in self._bias],
                0.9, 0.999, 10 ** -8
            ]
        elif name == "Momentum":
            self._optimizer_params = [
                [np.zeros(weight.shape) for weight in self._weights],
                [np.zeros(bias.shape) for bias in self._bias],
                0.5, 0.499 / self._epoch, 0
            ]
        elif name == "RMSProp":
            self._optimizer_params = [
                [np.zeros(weight.shape) for weight in self._weights],
                [np.zeros(bias.shape) for bias in self._bias],
                0.9, 10 ** -8
            ]
        elif name == "CF0910":
            self._optimizer_params = [
                [np.zeros(weight.shape) for weight in self._weights],
                0.5, -4 * 0.49 / self._epoch ** 2, 0.49 * 4 / self._epoch, 0
            ]

    @NNTiming.timeit(level=1)
    def _update_optimizer(self, name):
        if name == "NAG" or name == "Momentum":
            self._optimizer_params[2] = 0.5 + self._optimizer_params[3] * self._optimizer_params[4]
            self._optimizer_params[4] += 1
        elif name == "CF0910":
            x = self._optimizer_params[4]
            self._optimizer_params[1] = 0.5 + self._optimizer_params[2] * x ** 2 + self._optimizer_params[3] * x
            self._optimizer_params[4] += 1

    @NNTiming.timeit(level=1)
    def _sgd(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        self._weights[i] += self._lr * _activation.T.dot(_delta)
        if self._whether_apply_bias:
            self._bias[i] += np.sum(_delta, axis=0, keepdims=True) * self._lr

    @NNTiming.timeit(level=1)
    def _nag(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        velocity, momentum = self._optimizer_params[0], self._optimizer_params[2]
        dw = self._lr * _activation.T.dot(_delta)
        velocity[i] = momentum * velocity[i] + dw
        self._weights[i] += velocity[i] * momentum + dw
        if self._whether_apply_bias:
            velocity = self._optimizer_params[1]
            db = self._lr * np.sum(_delta, axis=0, keepdims=True)
            velocity[i] = momentum * velocity[i] + db
            self._bias[i] += velocity[i] * momentum + db

    @NNTiming.timeit(level=1)
    def _adam(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        dx = _activation.T.dot(_delta)
        beta1, beta2, eps = self._optimizer_params[4:]
        self._optimizer_params[0][i] = self._optimizer_params[0][i] * beta1 + (1 - beta1) * dx
        self._optimizer_params[1][i] = self._optimizer_params[1][i] * beta2 + (1 - beta2) * (dx ** 2)
        self._weights[i] += self._lr * self._optimizer_params[0][i] / (np.sqrt(self._optimizer_params[1][i] + eps))
        if self._whether_apply_bias:
            db = np.sum(_delta, axis=0, keepdims=True)
            self._optimizer_params[2][i] = self._optimizer_params[2][i] * beta1 + (1 - beta1) * db
            self._optimizer_params[3][i] = self._optimizer_params[3][i] * beta2 + (1 - beta2) * (db ** 2)
            self._bias[i] += self._lr * self._optimizer_params[2][i] / (np.sqrt(self._optimizer_params[3][i] + eps))

    @NNTiming.timeit(level=1)
    def _momentum(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        velocity, momentum = self._optimizer_params[0], self._optimizer_params[2]
        velocity[i] = velocity[i] * momentum + self._lr * _activation.T.dot(_delta)
        self._weights[i] += velocity[i]
        if self._whether_apply_bias:
            velocity = self._optimizer_params[1]
            velocity[i] = velocity[i] * momentum + self._lr * np.sum(_delta, axis=0, keepdims=True)
            self._bias[i] += velocity[i]

    @NNTiming.timeit(level=1)
    def _rmsprop(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        dw = _activation.T.dot(_delta)
        decay_rate, eps = self._optimizer_params[2:]
        self._optimizer_params[0][i] = self._optimizer_params[0][i] * decay_rate + (1 - decay_rate) * dw ** 2
        self._weights[i] += self._lr * dw / (np.sqrt(self._optimizer_params[0][i] + eps))
        if self._whether_apply_bias:
            db = np.sum(_delta, axis=0, keepdims=True)
            self._optimizer_params[1][i] = self._optimizer_params[1][i] * decay_rate + (1 - decay_rate) * db ** 2
            self._bias[i] += self._lr * db / (np.sqrt(self._optimizer_params[1][i] + eps))

    @NNTiming.timeit(level=1)
    def _cf0910(self, i, _activation, _delta):
        self._weights[i] *= self._regularization_param
        velocity, momentum = self._optimizer_params[0], self._optimizer_params[1]
        dw = self._lr * _activation.T.dot(_delta)
        velocity[i] = momentum * velocity[i] + dw
        self._weights[i] += velocity[i] * momentum + dw
        if self._whether_apply_bias:
            self._bias[i] += self._lr * np.sum(_delta, axis=0, keepdims=True)

    # API

    @NNTiming.timeit(level=4, prefix="[API] ")
    def feed(self, x, y):
        self._feed_data(x, y)

    @NNTiming.timeit(level=4, prefix="[API] ")
    def add(self, layer, *args):
        if isinstance(layer, str):
            self._add_layer(layer, *args)
        else:
            if not isinstance(layer, Layer):
                raise BuildLayerError("Invalid Layer provided (should be subclass of Layer)")
            if not self._layers:
                if isinstance(layer, SubLayer):
                    raise BuildLayerError("Invalid Layer provided (first layer should not be subclass of SubLayer)")
                if len(layer.shape) != 2:
                    raise BuildLayerError("Invalid input Layer provided (shape should be {}, {} found)".format(
                        2, len(layer.shape)
                    ))
                self._layers, self._current_dimension = [layer], layer.shape[1]
                self._update_layer_information(None)
                self._add_weight(layer.shape)
            else:
                if len(layer.shape) > 2:
                    raise BuildLayerError("Invalid Layer provided (shape should be {}, {} found)".format(
                        2, len(layer.shape)
                    ))
                if len(layer.shape) == 2:
                    _current, _next = layer.shape
                    if isinstance(layer, SubLayer):
                        if _next != self._current_dimension:
                            raise BuildLayerError("Invalid SubLayer provided (shape[1] should be {}, {} found)".format(
                                self._current_dimension, _next
                            ))
                    elif _current != self._current_dimension:
                        raise BuildLayerError("Invalid Layer provided (shape[0] should be {}, {} found)".format(
                            self._current_dimension, _current
                        ))
                    self._add_layer(layer, _current, _next)

                elif len(layer.shape) == 1:
                    _next = layer.shape[0]
                    layer.shape = (self._current_dimension, _next)
                    self._add_layer(layer, self._current_dimension, _next)
                else:
                    raise LayerError("Invalid Layer provided (invalid shape '{}' found)".format(layer.shape))

    @NNTiming.timeit(level=4, prefix="[API] ")
    def build(self, units="build"):
        if isinstance(units, str):
            if units == "build":
                for name, shape, param in zip(self._layer_names, self._layer_shapes, self._layer_params):
                    try:
                        self.add(self._available_root_layers[name](shape))
                    except KeyError:
                        self.add(name, param)
                self._add_cost_layer()
            else:
                raise NotImplementedError("Invalid param '{}' provided to 'build' method".format(units))
        else:
            try:
                units = np.array(units).flatten().astype(np.int)
            except ValueError as err:
                raise BuildLayerError(err)
            if len(units) < 2:
                raise BuildLayerError("At least 2 layers are needed")
            _input_shape = (units[0], units[1])
            self.initialize()
            self.add(Sigmoid(_input_shape))
            for unit_num in units[2:]:
                self.add(Sigmoid((unit_num,)))
            self._add_cost_layer()

    @NNTiming.timeit(level=4, prefix="[API] ")
    def preview(self, add_cost=True):
        if not self._layers:
            rs = "None"
        else:
            if add_cost:
                self._add_cost_layer()
            rs = (
                "Input  :  {:<10s} - {}\n".format("Dimension", self._layers[0].shape[0]) +
                "\n".join(["Layer  :  {:<10s} - {}".format(
                    _layer.name, _layer.shape[1]
                ) if _layer.name not in self._available_sub_layers else "Layer  :  {:<10s} - {} {}".format(
                    _layer.name, _layer.shape[1], _layer.description
                ) for _layer in self._layers[:-1]]) +
                "\nCost   :  {:<10s}".format(self._cost_layer)
            )
        print("=" * 30 + "\n" + "Structure\n" + "-" * 30 + "\n" + rs + "\n" + "-" * 30 + "\n")

    @staticmethod
    @NNTiming.timeit(level=4, prefix="[API] ")
    def split_data(x, y, train_only, training_scale=TRAINING_SCALE, cv_scale=CV_SCALE):
        if train_only:
            train_len = len(x)
            x_train, y_train = np.array(x[:train_len]), np.array(y[:train_len])
            x_cv, y_cv, x_test, y_test = x_train, y_train, x_train, y_train
        else:
            shuffle_suffix = np.random.permutation(len(x))
            x, y = x[shuffle_suffix], y[shuffle_suffix]
            train_len = int(len(x) * training_scale)
            cv_len = train_len + int(len(x) * cv_scale)
            x_train, y_train = np.array(x[:train_len]), np.array(y[:train_len])
            x_cv, y_cv = np.array(x[train_len:cv_len]), np.array(y[train_len:cv_len])
            x_test, y_test = np.array(x[cv_len:]), np.array(y[cv_len:])

        if BOOST_LESS_SAMPLES:
            if y_train.shape[1] != 2:
                raise BuildNetworkError("It is not permitted to boost less samples in multiple classification")
            y_train_arg = np.argmax(y_train, axis=1)
            y0 = y_train_arg == 0
            y1 = ~y0
            y_len, y0_len = len(y_train), int(np.sum(y0))
            if y0_len > 0.5 * y_len:
                y0, y1 = y1, y0
                y0_len = y_len - y0_len
            boost_suffix = np.random.randint(y0_len, size=y_len - y0_len)
            x_train = np.vstack((x_train[y1], x_train[y0][boost_suffix]))
            y_train = np.vstack((y_train[y1], y_train[y0][boost_suffix]))
            shuffle_suffix = np.random.permutation(len(x_train))
            x_train, y_train = x_train[shuffle_suffix], y_train[shuffle_suffix]

        return (x_train, x_cv, x_test), (y_train, y_cv, y_test)

    @NNTiming.timeit(level=1, prefix="[API] ")
    def fit(self,
            x=None, y=None, optimizer=None, batch_size=512, record_period=1,
            lr=0.01, lb=0.01, epoch=20, apply_bias=True,
            show_loss=False, train_only=False,
            metrics=None, do_log=False, print_log=False, debug=False,
            visualize=False, visualize_setting=None,
            draw_weights=False, draw_network=False, draw_detailed_network=False,
            draw_img_network=False, img_shape=None,
            weight_average=None):

        if draw_img_network and img_shape is None:
            raise BuildNetworkError("Please provide image's shape to draw_img_network")

        x, y = self._feed_data(x, y)
        self._lr, self._epoch = lr, epoch
        if self._optimizer is None:
            if optimizer is None:
                self._optimizer = self._rmsprop
                self._optimizer_name = "RMSProp"
            elif optimizer not in self._available_optimizers:
                raise BuildNetworkError("Invalid Optimizer '{}' found".format(optimizer))
            else:
                self._optimizer = self._available_optimizers[optimizer]
                self._optimizer_name = optimizer
        self._init_optimizer()

        if not self._layers:
            raise BuildNetworkError("Please provide layers before fitting data")
        self._add_cost_layer()

        if y.shape[1] != self._current_dimension:
            raise BuildNetworkError("Output layer's shape should be {}, {} found".format(
                self._current_dimension, y.shape[1]))

        (x_train, x_cv, x_test), (y_train, y_cv, y_test) = NN.split_data(x, y, train_only)
        train_len = len(x_train)
        batch_size = min(batch_size, train_len)
        do_random_batch = train_len >= batch_size
        train_repeat = int(train_len / batch_size) + 1
        self._regularization_param = 1 - lb * lr / batch_size
        self._feed_data(x_train, y_train)

        self._metrics = ["acc"] if metrics is None else metrics
        for i, metric in enumerate(self._metrics):
            if isinstance(metric, str):
                if metric not in self._available_metrics:
                    raise BuildNetworkError("Metric '{}' is not implemented".format(metric))
                self._metrics[i] = self._available_metrics[metric]
        self._metric_names = [_m.__name__ for _m in self._metrics]

        self._logs = [[] for _ in range(len(self._metrics) + 1)]

        layer_width = len(self._layers)
        self._whether_apply_bias = apply_bias

        bar = ProgressBar(min_value=0, max_value=max(1, epoch // record_period))
        bar.start()
        img = None

        weight_trace = [[[org] for org in weight] for weight in self._weights]

        for counter in range(epoch):
            self._update_optimizer(optimizer)
            _activations = []
            for _ in range(train_repeat):

                if do_random_batch:
                    batch = np.random.randint(train_len, size=batch_size)
                    x_batch, y_batch = x_train[batch], y_train[batch]
                else:
                    x_batch, y_batch = x_train, y_train

                _activations = self._get_activations(x_batch)

                _deltas = [self._layers[-1].bp_first(y_batch, _activations[-1])]
                for i in range(-1, -len(_activations), -1):
                    _deltas.append(self._layers[i - 1].bp(_activations[i - 1], self._weights[i], _deltas[-1]))

                for i in range(layer_width - 1, 0, -1):
                    if not isinstance(self._layers[i], SubLayer):
                        self._optimizer(i, _activations[i - 1], _deltas[layer_width - i - 1])
                self._optimizer(0, x_batch, _deltas[-1])

                if draw_weights:
                    for i, weight in enumerate(self._weights):
                        for j, new_weight in enumerate(weight.copy()):
                            weight_trace[i][j].append(new_weight)

                if debug:
                    pass

            if do_log:
                self._append_log(x_cv, y_cv, get_loss=show_loss)

            if (counter + 1) % record_period == 0:
                if do_log and print_log:
                    self._print_metric_logs(x_cv, y_cv, show_loss)
                if visualize:
                    if visualize_setting is None:
                        self.do_visualization(x_cv, y_cv)
                    else:
                        self.do_visualization(x_cv, y_cv, *visualize_setting)
                if x_cv.shape[1] == 2:
                    if draw_network:
                        img = self.draw_network(weight_average=weight_average, activations=_activations)
                    if draw_detailed_network:
                        img = self.draw_detailed_network(weight_average=weight_average)
                elif draw_img_network:
                    img = self.draw_img_network(img_shape, weight_average=weight_average)
                bar.update(counter // record_period + 1)

        if do_log:
            self._append_log(x_test, y_test, get_loss=show_loss)
        if img is not None:
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        if draw_weights:
            ts = np.arange(epoch * train_repeat + 1)
            for i, weight in enumerate(self._weights):
                plt.figure()
                for j in range(len(weight)):
                    plt.plot(ts, weight_trace[i][j])
                plt.show()

        return self._logs

    @NNTiming.timeit(level=2, prefix="[API] ")
    def save(self, path=None, name=None, overwrite=True):

        path = "Models" if path is None else path
        name = "Model.nn" if name is None else name
        if not os.path.exists(path):
            os.mkdir(path)
        slash = "\\" if platform.system() == "Windows" else "/"

        _dir = path + slash + name
        if not overwrite and os.path.isfile(_dir):
            _count = 1
            _new_dir = _dir + "({})".format(_count)
            while os.path.isfile(_new_dir):
                _count += 1
                _new_dir = _dir + "({})".format(_count)
            _dir = _new_dir

        with open(_dir, "wb") as file:
            pickle.dump({
                "_logs": self._logs,
                "_metric_names": self._metric_names,
                "_layer_names": self.layer_names,
                "_layer_shapes": self.layer_shapes,
                "_layer_params": self._layer_params,
                "_cost_layer": self._layers[-1].name,
                "_weights": self._weights,
                "_bias": self._bias,
                "_optimizer_name": self._optimizer_name,
                "_next_dimension": self._current_dimension
            }, file)

    @NNTiming.timeit(level=2, prefix="[API] ")
    def load(self, path):
        self.initialize()
        try:
            with open(path, "rb") as file:
                _dic = pickle.load(file)
                for key, value in _dic.items():
                    setattr(self, key, value)
                self.build()
                for i in range(len(self._metric_names) - 1, -1, -1):
                    name = self._metric_names[i]
                    if name not in self._available_metrics:
                        self._metric_names.pop(i)
                    else:
                        self._metrics.insert(0, self._available_metrics[name])
                return _dic
        except Exception as err:
            raise BuildNetworkError("Failed to load Network ({}), structure initialized".format(err))

    @NNTiming.timeit(level=4, prefix="[API] ")
    def predict(self, x):
        x = np.array(x)
        if len(x.shape) == 1:
            x = x.reshape((1, len(x)))
        return self._get_prediction(x)

    @NNTiming.timeit(level=4, prefix="[API] ")
    def predict_classes(self, x, flatten=True):
        x = np.array(x)
        if len(x.shape) == 1:
            x = x.reshape((1, len(x)))
        if flatten:
            return np.argmax(self._get_prediction(x), axis=1)
        return np.argmax([self._get_prediction(x)], axis=2).T

    @NNTiming.timeit(level=4, prefix="[API] ")
    def evaluate(self, x, y, metrics=None):
        if metrics is None:
            metrics = self._metrics
        else:
            for i in range(len(metrics) - 1, -1, -1):
                metric = metrics[i]
                if isinstance(metric, str):
                    if metric not in self._available_metrics:
                        metrics.pop(i)
                    else:
                        metrics[i] = self._available_metrics[metric]
        logs, y_pred = [], self._get_prediction(x)
        for metric in metrics:
            logs.append(metric(y, y_pred))
        return logs

    @NNTiming.timeit(level=5, prefix="[API] ")
    def do_visualization(self, x=None, y=None, plot_scale=2, plot_precision=0.01):

        x = self._x if x is None else x
        y = self._y if y is None else y

        plot_num = int(1 / plot_precision)

        xf = np.linspace(self._x_min * plot_scale, self._x_max * plot_scale, plot_num)
        yf = np.linspace(self._x_min * plot_scale, self._x_max * plot_scale, plot_num)
        input_x, input_y = np.meshgrid(xf, yf)
        input_xs = np.c_[input_x.ravel(), input_y.ravel()]

        if self._x.shape[1] != 2:
            output_ys_2d = np.argmax(
                self.predict(np.c_[input_xs, self._x[:, 2:][0]]), axis=1).reshape((len(xf), len(yf)))
            output_ys_3d = self.predict(
                np.c_[input_xs, self._x[:, 2:][0]])[:, 0].reshape((len(xf), len(yf)))
        else:
            output_ys_2d = np.argmax(self.predict(input_xs), axis=1).reshape((len(xf), len(yf)))
            output_ys_3d = self.predict(input_xs)[:, 0].reshape((len(xf), len(yf)))

        xf, yf = np.meshgrid(xf, yf, sparse=True)

        plt.contourf(input_x, input_y, output_ys_2d, cmap=cm.Spectral)
        plt.scatter(x[:, 0], x[:, 1], c=np.argmax(y, axis=1), s=40, cmap=cm.Spectral)
        plt.axis("off")
        plt.show()

        if self._y.shape[1] == 2:
            fig = plt.figure()
            ax = fig.add_subplot(111, projection='3d')

            ax.plot_surface(xf, yf, output_ys_3d, cmap=cm.coolwarm, )
            ax.set_xlabel("x")
            ax.set_ylabel("y")
            ax.set_zlabel("z")
            plt.show()

    @NNTiming.timeit(level=1, prefix="[API] ")
    def draw_network(self, radius=6, width=1200, height=800, padding=0.2, sub_layer_height_scale=0, delay=1,
                     weight_average=None, activations=None):

        layers = len(self._layers) + 1
        units = [layer.shape[0] for layer in self._layers] + [self._layers[-1].shape[1]]
        whether_sub_layers = np.array([False] + [isinstance(layer, SubLayer) for layer in self._layers])
        n_sub_layers = int(np.sum(whether_sub_layers))

        img = np.zeros((height, width, 3), np.uint8)
        axis0_padding = int(height / (layers - 1 + 2 * padding)) * padding
        axis0_step = (height - 2 * axis0_padding) / layers
        sub_layer_decrease = int((1 - sub_layer_height_scale) * axis0_step)
        axis0 = np.linspace(
            axis0_padding,
            height + n_sub_layers * sub_layer_decrease - axis0_padding,
            layers, dtype=np.int)
        axis0 -= sub_layer_decrease * np.cumsum(whether_sub_layers)
        axis1_divide = [int(width / (unit + 1)) for unit in units]
        axis1 = [np.linspace(divide, width - divide, units[i], dtype=np.int)
                 for i, divide in enumerate(axis1_divide)]

        colors, thicknesses = [], []
        color_weights = [weight.copy() for weight in self._weights]
        color_min = [np.min(weight) for weight in color_weights]
        color_max = [np.max(weight) for weight in color_weights]
        color_average = [np.average(weight) for weight in color_weights] if weight_average is None else weight_average
        for weight, weight_min, weight_max, weight_average in zip(
            color_weights, color_min, color_max, color_average
        ):
            line_info = get_line_info(weight, weight_min, weight_max, weight_average)
            colors.append(line_info[0])
            thicknesses.append(line_info[1])

        activations = [np.average(np.abs(activation), axis=0) for activation in activations]
        activations = [activation / np.max(activation) for activation in activations]
        for i, (y, xs) in enumerate(zip(axis0, axis1)):
            for j, x in enumerate(xs):
                if i == 0:
                    cv2.circle(img, (x, y), radius, (20, 215, 20), int(radius / 2))
                else:
                    activation = activations[i - 1][j]
                    try:
                        cv2.circle(img, (x, y), radius, (
                            int(255 * activation), int(255 * activation), int(255 * activation)), int(radius / 2))
                    except ValueError:
                        cv2.circle(img, (x, y), radius, (0, 0, 255), int(radius / 2))
            if i > 0:
                cv2.putText(img, self._layers[i - 1].name, (12, y - 36), cv2.LINE_AA, 0.6, (255, 255, 255), 2)

        for i, y in enumerate(axis0):
            if i == len(axis0) - 1:
                break
            for j, x in enumerate(axis1[i]):
                new_y = axis0[i + 1]
                whether_sub_layer = isinstance(self._layers[i], SubLayer)
                for k, new_x in enumerate(axis1[i + 1]):
                    if whether_sub_layer and j != k:
                        continue
                    cv2.line(img, (x, y), (new_x, new_y), colors[i][j][k], thicknesses[i][j][k])

        cv2.imshow("Neural Network", img)
        cv2.waitKey(delay)
        return img

    @NNTiming.timeit(level=1, prefix="[API] ")
    def draw_detailed_network(self, radius=6, width=1200, height=800, padding=0.2,
                              plot_scale=2, plot_precision=0.03,
                              sub_layer_height_scale=0, delay=1,
                              weight_average=None):

        layers = len(self._layers) + 1
        units = [layer.shape[0] for layer in self._layers] + [self._layers[-1].shape[1]]
        whether_sub_layers = np.array([False] + [isinstance(layer, SubLayer) for layer in self._layers])
        n_sub_layers = int(np.sum(whether_sub_layers))

        plot_num = int(1 / plot_precision)
        if plot_num % 2 == 1:
            plot_num += 1
        half_plot_num = int(plot_num * 0.5)
        xf = np.linspace(self._x_min * plot_scale, self._x_max * plot_scale, plot_num)
        yf = np.linspace(self._x_min * plot_scale, self._x_max * plot_scale, plot_num) * -1
        input_x, input_y = np.meshgrid(xf, yf)
        input_xs = np.c_[input_x.ravel(), input_y.ravel()]

        _activations = [activation.T.reshape(units[i + 1], plot_num, plot_num)
                        for i, activation in enumerate(self._get_activations(input_xs))]
        _graphs = []
        for j, activation in enumerate(_activations):
            _graph_group = []
            for ac in activation:
                data = np.zeros((plot_num, plot_num, 3), np.uint8)
                mask = ac >= np.average(ac)
                data[mask], data[~mask] = [0, 125, 255], [255, 125, 0]
                _graph_group.append(data)
            _graphs.append(_graph_group)

        img = np.zeros((height, width, 3), np.uint8)
        axis0_padding = int(height / (layers - 1 + 2 * padding)) * padding + plot_num
        axis0_step = (height - 2 * axis0_padding) / layers
        sub_layer_decrease = int((1 - sub_layer_height_scale) * axis0_step)
        axis0 = np.linspace(
            axis0_padding,
            height + n_sub_layers * sub_layer_decrease - axis0_padding,
            layers, dtype=np.int)
        axis0 -= sub_layer_decrease * np.cumsum(whether_sub_layers)
        axis1_padding = plot_num
        axis1 = [np.linspace(axis1_padding, width - axis1_padding, unit + 2, dtype=np.int)
                 for unit in units]
        axis1 = [axis[1:-1] for axis in axis1]

        colors, thicknesses = [], []
        color_weights = [weight.copy() for weight in self._weights]
        color_min = [np.min(weight) for weight in color_weights]
        color_max = [np.max(weight) for weight in color_weights]
        color_average = [np.average(weight) for weight in color_weights] if weight_average is None else weight_average
        for weight, weight_min, weight_max, weight_average in zip(
            color_weights, color_min, color_max, color_average
        ):
            line_info = get_line_info(weight, weight_min, weight_max, weight_average)
            colors.append(line_info[0])
            thicknesses.append(line_info[1])

        for i, (y, xs) in enumerate(zip(axis0, axis1)):
            for j, x in enumerate(xs):
                if i == 0:
                    cv2.circle(img, (x, y), radius, (20, 215, 20), int(radius / 2))
                else:
                    graph = _graphs[i - 1][j]
                    img[y-half_plot_num:y+half_plot_num, x-half_plot_num:x+half_plot_num] = graph
            if i > 0:
                cv2.putText(img, self._layers[i - 1].name, (12, y - 36), cv2.LINE_AA, 0.6, (255, 255, 255), 2)

        for i, y in enumerate(axis0):
            if i == len(axis0) - 1:
                break
            for j, x in enumerate(axis1[i]):
                new_y = axis0[i + 1]
                whether_sub_layer = isinstance(self._layers[i], SubLayer)
                for k, new_x in enumerate(axis1[i + 1]):
                    if whether_sub_layer and j != k:
                        continue
                    cv2.line(img, (x, y+half_plot_num), (new_x, new_y-half_plot_num),
                             colors[i][j][k], thicknesses[i][j][k])

        cv2.imshow("Neural Network", img)
        cv2.waitKey(delay)
        return img

    @NNTiming.timeit(level=1, prefix="[API] ")
    def draw_img_network(self, img_shape, width=1200, height=800, padding=0.2,
                         sub_layer_height_scale=0, delay=1,
                         weight_average=None):

        img_width, img_height = img_shape
        half_width = int(img_width * 0.5) if img_width % 2 == 0 else int(img_width * 0.5) + 1
        half_height = int(img_height * 0.5) if img_height % 2 == 0 else int(img_height * 0.5) + 1

        layers = len(self._layers)
        units = [layer.shape[1] for layer in self._layers]
        whether_sub_layers = np.array([isinstance(layer, SubLayer) for layer in self._layers])
        n_sub_layers = int(np.sum(whether_sub_layers))

        _activations = [self._weights[0].copy().T]
        for weight in self._weights[1:]:
            _activations.append(weight.T.dot(_activations[-1]))
        _graphs = []
        for j, activation in enumerate(_activations):
            _graph_group = []
            for ac in activation:
                ac = ac.reshape((img_width, img_height))
                ac -= np.average(ac)
                data = np.zeros((img_width, img_height, 3), np.uint8)
                mask = ac >= 0.25
                data[mask], data[~mask] = [0, 130, 255], [255, 130, 0]
                _graph_group.append(data)
            _graphs.append(_graph_group)

        img = np.zeros((height, width, 3), np.uint8)
        axis0_padding = int(height / (layers - 1 + 2 * padding)) * padding + img_height
        axis0_step = (height - 2 * axis0_padding) / layers
        sub_layer_decrease = int((1 - sub_layer_height_scale) * axis0_step)
        axis0 = np.linspace(
            axis0_padding,
            height + n_sub_layers * sub_layer_decrease - axis0_padding,
            layers, dtype=np.int)
        axis0 -= sub_layer_decrease * np.cumsum(whether_sub_layers)
        axis1_padding = img_width
        axis1 = [np.linspace(axis1_padding, width - axis1_padding, unit + 2, dtype=np.int)
                 for unit in units]
        axis1 = [axis[1:-1] for axis in axis1]

        colors, thicknesses = [], []
        color_weights = [weight.copy() for weight in self._weights]
        color_min = [np.min(weight) for weight in color_weights]
        color_max = [np.max(weight) for weight in color_weights]
        color_average = [np.average(weight) for weight in color_weights] if weight_average is None else weight_average
        for weight, weight_min, weight_max, weight_average in zip(
            color_weights, color_min, color_max, color_average
        ):
            line_info = get_line_info(weight, weight_min, weight_max, weight_average)
            colors.append(line_info[0])
            thicknesses.append(line_info[1])

        for i, (y, xs) in enumerate(zip(axis0, axis1)):
            for j, x in enumerate(xs):
                graph = _graphs[i][j]
                img[y - half_height:y + half_height, x - half_width:x + half_width] = graph
            cv2.putText(img, self._layers[i].name, (12, y - 36), cv2.LINE_AA, 0.6, (255, 255, 255), 2)

        for i, y in enumerate(axis0):
            if i == len(axis0) - 1:
                break
            for j, x in enumerate(axis1[i]):
                new_y = axis0[i + 1]
                whether_sub_layer = isinstance(self._layers[i + 1], SubLayer)
                for k, new_x in enumerate(axis1[i + 1]):
                    if whether_sub_layer and j != k:
                        continue
                    cv2.line(img, (x, y + half_height), (new_x, new_y - half_height),
                             colors[i + 1][j][k], thicknesses[i + 1][j][k])

        cv2.imshow("Neural Network", img)
        cv2.waitKey(delay)
        return img

    @staticmethod
    def fuck_pycharm_warning():
        print(Axes3D.acorr)
