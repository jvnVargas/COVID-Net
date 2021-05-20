# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""ResNet50 backbone used in DELF model.
Copied over from tensorflow/python/eager/benchmarks/resnet50/resnet50.py,
because that code does not support dependencies.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from tensorflow.keras.models import Model
import functools
import os
import tempfile

from absl import logging
import h5py
import tensorflow as tf
from tensorflow.keras.layers import Input

layers = tf.keras.layers


class _IdentityBlock(tf.keras.Model):
    """_IdentityBlock is the block that has no conv layer at shortcut.
    Args:
      kernel_size: the kernel size of middle conv layer at main path
      filters: list of integers, the filters of 3 conv layer at main path
      stage: integer, current stage label, used for generating layer names
      block: 'a','b'..., current block label, used for generating layer names
      data_format: data_format for the input ('channels_first' or
        'channels_last').
    """

    def __init__(self, kernel_size, filters, stage, block, data_format):
        super(_IdentityBlock, self).__init__(name='')
        filters1, filters2, filters3 = filters

        conv_name_base = 'res' + str(stage) + block + '_branch'
        bn_name_base = 'bn' + str(stage) + block + '_branch'
        bn_axis = 1 if data_format == 'channels_first' else 3

        self.conv2a = layers.Conv2D(
            filters1, (1, 1), name=conv_name_base + '2a', data_format=data_format)
        self.bn2a = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2a')

        self.conv2b = layers.Conv2D(
            filters2,
            kernel_size,
            padding='same',
            data_format=data_format,
            name=conv_name_base + '2b')
        self.bn2b = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2b')

        self.conv2c = layers.Conv2D(
            filters3, (1, 1), name=conv_name_base + '2c', data_format=data_format)
        self.bn2c = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2c')

    def call(self, input_tensor, training=False):
        x = self.conv2a(input_tensor)
        x = self.bn2a(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2b(x)
        x = self.bn2b(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2c(x)
        x = self.bn2c(x, training=training)

        x += input_tensor
        return tf.nn.relu(x)


class _ConvBlock(tf.keras.Model):
    """_ConvBlock is the block that has a conv layer at shortcut.
    Args:
        kernel_size: the kernel size of middle conv layer at main path
        filters: list of integers, the filters of 3 conv layer at main path
        stage: integer, current stage label, used for generating layer names
        block: 'a','b'..., current block label, used for generating layer names
        data_format: data_format for the input ('channels_first' or
          'channels_last').
        strides: strides for the convolution. Note that from stage 3, the first
          conv layer at main path is with strides=(2,2), and the shortcut should
          have strides=(2,2) as well.
    """

    def __init__(self,
                 kernel_size,
                 filters,
                 stage,
                 block,
                 data_format,
                 strides=(2, 2)):
        super(_ConvBlock, self).__init__(name='')
        filters1, filters2, filters3 = filters

        conv_name_base = 'res' + str(stage) + block + '_branch'
        bn_name_base = 'bn' + str(stage) + block + '_branch'
        bn_axis = 1 if data_format == 'channels_first' else 3

        self.conv2a = layers.Conv2D(
            filters1, (1, 1),
            strides=strides,
            name=conv_name_base + '2a',
            data_format=data_format)
        self.bn2a = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2a')

        self.conv2b = layers.Conv2D(
            filters2,
            kernel_size,
            padding='same',
            name=conv_name_base + '2b',
            data_format=data_format)
        self.bn2b = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2b')

        self.conv2c = layers.Conv2D(
            filters3, (1, 1), name=conv_name_base + '2c', data_format=data_format)
        self.bn2c = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '2c')

        self.conv_shortcut = layers.Conv2D(
            filters3, (1, 1),
            strides=strides,
            name=conv_name_base + '1',
            data_format=data_format)
        self.bn_shortcut = layers.BatchNormalization(
            axis=bn_axis, name=bn_name_base + '1')

    def call(self, input_tensor, training=False):
        x = self.conv2a(input_tensor)
        x = self.bn2a(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2b(x)
        x = self.bn2b(x, training=training)
        x = tf.nn.relu(x)

        x = self.conv2c(x)
        x = self.bn2c(x, training=training)

        shortcut = self.conv_shortcut(input_tensor)
        shortcut = self.bn_shortcut(shortcut, training=training)

        x += shortcut
        return tf.nn.relu(x)


# pylint: disable=not-callable
class ResNet50_1(tf.keras.Model):
    """Instantiates the ResNet50 architecture.
    Args:
      data_format: format for the image. Either 'channels_first' or
        'channels_last'.  'channels_first' is typically faster on GPUs while
        'channels_last' is typically faster on CPUs. See
        https://www.tensorflow.org/performance/performance_guide#data_formats
      name: Prefix applied to names of variables created in the model.
      include_top: whether to include the fully-connected layer at the top of the
        network.
      pooling: Optional pooling mode for feature extraction when `include_top` is
        False. 'None' means that the output of the model will be the 4D tensor
        output of the last convolutional layer. 'avg' means that global average
        pooling will be applied to the output of the last convolutional layer, and
        thus the output of the model will be a 2D tensor. 'max' means that global
        max pooling will be applied. 'gem' means GeM pooling will be applied.
      block3_strides: whether to add a stride of 2 to block3 to make it compatible
        with tf.slim ResNet implementation.
      average_pooling: whether to do average pooling of block4 features before
        global pooling.
      classes: optional number of classes to classify images into, only to be
        specified if `include_top` is True.
      gem_power: GeM power for GeM pooling. Only used if pooling == 'gem'.
      embedding_layer: whether to create an embedding layer (FC whitening layer).
      embedding_layer_dim: size of the embedding layer.
    Raises:
        ValueError: in case of invalid argument for data_format.
    """

    def __init__(self,
                 data_format='channels_last',
                 name='',
                 model_semantic=None,
                 include_top=True,
                 pooling=None,
                 block3_strides=False,
                 average_pooling=True,
                 classes=2,
                 gem_power=3.0,
                 embedding_layer=False,
                 embedding_layer_dim=2):
        super(ResNet50_1, self).__init__(name=name)

        valid_channel_values = ('channels_first', 'channels_last')
        if data_format not in valid_channel_values:
            raise ValueError('Unknown data_format: %s. Valid values: %s' %
                             (data_format, valid_channel_values))
        self.include_top = include_top
        self.block3_strides = block3_strides
        self.average_pooling = average_pooling
        self.pooling = pooling
        self.model_semantic=model_semantic

        def conv_block(filters, stage, block, strides=(2, 2)):
            return _ConvBlock(
                3,
                filters,
                stage=stage,
                block=block,
                data_format=data_format,
                strides=strides)

        def id_block(filters, stage, block):
            return _IdentityBlock(
                3, filters, stage=stage, block=block, data_format=data_format)

        self.conv1 = layers.Conv2D(
            64, (7, 7),
            strides=(2, 2),
            data_format=data_format,
            padding='same',
            name='conv1')
        bn_axis = 1 if data_format == 'channels_first' else 3
        self.bn_conv1 = layers.BatchNormalization(axis=bn_axis, name='bn_conv1')
        self.max_pool = layers.MaxPooling2D((3, 3),
                                            strides=(2, 2),
                                            data_format=data_format)

        self.l2a = conv_block([64, 64, 256], stage=2, block='a', strides=(1, 1))
        self.l2b = id_block([64, 64, 256], stage=2, block='b')
        self.l2c = id_block([64, 64, 256], stage=2, block='c')

        self.l3a = conv_block([128, 128, 512], stage=3, block='a')
        self.l3b = id_block([128, 128, 512], stage=3, block='b')
        self.l3c = id_block([128, 128, 512], stage=3, block='c')
        self.l3d = id_block([128, 128, 512], stage=3, block='d')

        self.l4a = conv_block([256, 256, 1024], stage=4, block='a')
        self.l4b = id_block([256, 256, 1024], stage=4, block='b')
        self.l4c = id_block([256, 256, 1024], stage=4, block='c')
        self.l4d = id_block([256, 256, 1024], stage=4, block='d')
        self.l4e = id_block([256, 256, 1024], stage=4, block='e')
        self.l4f = id_block([256, 256, 1024], stage=4, block='f')

        # Striding layer that can be used on top of block3 to produce feature maps
        # with the same resolution as the TF-Slim implementation.
        if self.block3_strides:
            self.subsampling_layer = layers.MaxPooling2D((1, 1),
                                                         strides=(2, 2),
                                                         data_format=data_format)
            self.l5a = conv_block([512, 512, 2048],
                                  stage=5,
                                  block='a',
                                  strides=(1, 1))
        else:
            self.l5a = conv_block([512, 512, 2048], stage=5, block='a')
        self.l5b = id_block([512, 512, 2048], stage=5, block='b')
        self.l5c = id_block([512, 512, 2048], stage=5, block='c')

        self.avg_pool = layers.AveragePooling2D((7, 7),
                                                strides=(7, 7),
                                                data_format=data_format)

        if self.include_top:
            self.flatten = layers.Flatten(name="flatten_last")
            self.fc1000 = layers.Dense(classes, name='final_output')
            self.soft = layers.Softmax()
        else:
            reduction_indices = [1, 2] if data_format == 'channels_last' else [2, 3]
            reduction_indices = tf.constant(reduction_indices)
            if pooling == 'avg':
                self.global_pooling = functools.partial(
                    tf.reduce_mean, axis=reduction_indices, keepdims=False)
            elif pooling == 'max':
                self.global_pooling = functools.partial(
                    tf.reduce_max, axis=reduction_indices, keepdims=False)
            else:
                self.global_pooling = None
            if embedding_layer:
                logging.info('Adding embedding layer with dimension %d',
                             embedding_layer_dim)
                self.embedding_layer = layers.Dense(
                    embedding_layer_dim, name="final_output")
            else:
                self.embedding_layer = None

    # This function maps the output semantic to the output of main network
    def set_attention(self,output_semantic, output_main, counter):
        fixed_image = tf.image.resize(output_semantic, output_main.shape[1:-1])
        return layers.Conv2D(filters=output_main.shape[-1], kernel_size=(7, 7),
                      strides=(1, 1), padding="same",
                      kernel_initializer="he_normal",
                      name="sem/" + str(counter))(fixed_image)

    def apply_attention(self,counter,output_s,x):
        x = x + x * self.set_attention(output_s, x, counter)
        return counter+1,x


    def build_call(self, input_shape, training=True, intermediates_dict=None):
        """Building the ResNet50 model.
        Args:
          inputs: Images to compute features for.
          training: Whether model is in training phase.
          intermediates_dict: `None` or dictionary. If not None, accumulate feature
            maps from intermediate blocks into the dictionary. ""
        Returns:
          Tensor with featuremap.
        """
        counter = 600
        output_s=self.model_semantic.output
        inputs = Input(shape=input_shape)
        x = self.conv1(inputs)
        x = self.bn_conv1(tf.cast(x,dtype="float32"), training=training)
        x = tf.nn.relu(x)
        if intermediates_dict is not None:
            intermediates_dict['block0'] = x

        x = self.max_pool(x)
        if intermediates_dict is not None:
            intermediates_dict['block0mp'] = x
        counter,x=self.apply_attention(counter,output_s,x)

        # Block 1 (equivalent to "conv2" in Resnet paper).
        x = self.l2a(x, training=training)
        x = self.l2b(x, training=training)
        x = self.l2c(x, training=training)
        if intermediates_dict is not None:
            intermediates_dict['block1'] = x

        counter, x = self.apply_attention(counter, output_s, x)

        # Block 2 (equivalent to "conv3" in Resnet paper).
        x = self.l3a(x, training=training)
        x = self.l3b(x, training=training)
        x = self.l3c(x, training=training)
        x = self.l3d(x, training=training)
        if intermediates_dict is not None:
            intermediates_dict['block2'] = x
        counter,x=self.apply_attention(counter,output_s,x)

        # Block 3 (equivalent to "conv4" in Resnet paper).
        x = self.l4a(x, training=training)
        x = self.l4b(x, training=training)
        x = self.l4c(x, training=training)
        x = self.l4d(x, training=training)
        x = self.l4e(x, training=training)
        x = self.l4f(x, training=training)
        counter,x=self.apply_attention(counter,output_s,x)

        if self.block3_strides:
            x = self.subsampling_layer(x)
            if intermediates_dict is not None:
                intermediates_dict['block3'] = x
        else:
            if intermediates_dict is not None:
                intermediates_dict['block3'] = x

        x = self.l5a(x, training=training)
        x = self.l5b(x, training=training)
        x = self.l5c(x, training=training)

        if self.average_pooling:
            x = self.avg_pool(x)
            if intermediates_dict is not None:
                intermediates_dict['block4'] = x
        else:
            if intermediates_dict is not None:
                intermediates_dict['block4'] = x

        if self.include_top:
            outputs= self.soft(self.fc1000(self.flatten(x)))
        elif self.global_pooling:
            outputs = self.global_pooling(x)
            if self.embedding_layer:
                outputs = self.embedding_layer(outputs)
        model = Model(inputs=(inputs, self.model_semantic.input), outputs=outputs)
        return model

    def call(self, input_shape, training=True, intermediates_dict=None):
        """Call the ResNet50 model.
        Args:
          input_shape: Images to compute features for.
          training: Whether model is in training phase.
          intermediates_dict: `None` or dictionary. If not None, accumulate feature
            maps from intermediate blocks into the dictionary. ""
        Returns:
          Tensor with featuremap.
        """
        return self.build_call(input_shape, training, intermediates_dict)


