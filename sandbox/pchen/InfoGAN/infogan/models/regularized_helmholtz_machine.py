from __future__ import print_function
from sandbox.pchen.InfoGAN.infogan.misc.distributions import Product, Distribution, Mixture
import prettytensor as pt
import tensorflow as tf
# from deconv import deconv2d
import sandbox.pchen.InfoGAN.infogan.misc.custom_ops
from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import leaky_rectify
from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import CustomPhase
import numpy as np


class RegularizedHelmholtzMachine(object):
    def __init__(self, output_dist, latent_spec, batch_size,
            image_shape, network_type, network_args=None, inference_dist=None, wnorm=False):
        """
        :type output_dist: Distribution
        :type latent_spec: list[(Distribution, bool)]
        :type batch_size: int
        :type network_type: string
        """
        self.network_args = network_args
        self.output_dist = output_dist
        self.latent_spec = latent_spec
        if len(latent_spec) == 1:
            self.latent_dist = latent_spec[0][0]
        else:
            self.latent_dist = Product([x for x, _ in latent_spec])
        if inference_dist is None:
            inference_dist = self.latent_dist
        self.inference_dist = inference_dist
        self.reg_latent_dist = Product([x for x, reg in latent_spec if reg])
        self.nonreg_latent_dist = Product([x for x, reg in latent_spec if not reg])
        self.batch_size = batch_size
        self.network_type = network_type
        self.image_shape = image_shape
        self.wnorm = wnorm
        self.book = pt.bookkeeper_for_default_graph()


        image_size = image_shape[0]

        with pt.defaults_scope(activation_fn=tf.nn.relu):
            if self.network_type == "large_conv":
                self.encoder_template = \
                    (pt.template("input").
                     reshape([-1] + list(image_shape)).
                     custom_conv2d(64, k_h=4, k_w=4).
                     apply(leaky_rectify).
                     custom_conv2d(128, k_h=4, k_w=4).
                     conv_batch_norm().
                     apply(leaky_rectify).
                     custom_fully_connected(1024).
                     fc_batch_norm().
                     apply(leaky_rectify).
                     custom_fully_connected(self.latent_dist.dist_flat_dim))
                self.reg_encoder_template = \
                    (pt.template("input").
                     reshape([-1] + list(image_shape)).
                     custom_conv2d(64, k_h=4, k_w=4).
                     apply(leaky_rectify).
                     custom_conv2d(128, k_h=4, k_w=4).
                     conv_batch_norm().
                     apply(leaky_rectify).
                     custom_fully_connected(1024).
                     fc_batch_norm().
                     apply(leaky_rectify).
                     custom_fully_connected(self.reg_latent_dist.dist_flat_dim))
                self.decoder_template = \
                    (pt.template("input").
                     custom_fully_connected(1024).
                     fc_batch_norm().
                     apply(tf.nn.relu).
                     custom_fully_connected(128 * image_size / 4 * image_size / 4).
                     fc_batch_norm().
                     apply(tf.nn.relu).
                     reshape([-1, image_size / 4, image_size / 4, 128]).
                     custom_deconv2d([0, image_size / 2, image_size / 2, 64], k_h=4, k_w=4).
                     conv_batch_norm().
                     apply(tf.nn.relu).
                     custom_deconv2d([0, image_size, image_size, 1], k_h=4, k_w=4).
                     flatten())
            elif self.network_type == "mlp":
                self.encoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(self.inference_dist.dist_flat_dim, activation_fn=None))
                self.reg_encoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
                self.decoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(self.output_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "deep_mlp":
                self.encoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(self.inference_dist.dist_flat_dim, activation_fn=None))
                self.reg_encoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
                self.decoder_template = \
                    (pt.template('input').
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(500).
                     fully_connected(self.output_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "conv1_k5":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(activation_fn=tf.nn.elu, custom_phase=UnboundVariable('custom_phase'), wnorm=self.wnorm):
                    self.encoder_template = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape)).
                         conv2d_mod(5, 16, ).
                         conv2d_mod(5, 16, residual=False).
                         conv2d_mod(5, 16, residual=False).
                         conv2d_mod(5, 32, stride=2). # out 32*14*14
                         conv2d_mod(5, 32, residual=False).
                         conv2d_mod(5, 32, residual=False).
                         conv2d_mod(5, 32, stride=2). # out 32*7*7
                         conv2d_mod(5, 32, residual=False).
                         conv2d_mod(5, 32, residual=False).
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    self.decoder_template = \
                        (pt.template('input', self.book).
                         wnorm_fc(450, ).
                         wnorm_fc(1568, ).
                         # fully_connected(450, ).
                         # fully_connected(1568, ).
                         reshape([-1, 7, 7, 32]).
                         # reshape([self.batch_size, 1, 1, 450]).
                         # custom_deconv2d([0] + [7,7,32], k_h=1, k_w=1).
                         conv2d_mod(5, 32, residual=False).
                         conv2d_mod(5, 32, residual=False).
                         custom_deconv2d([0] + [14,14,32], k_h=5, k_w=5).
                         conv2d_mod(5, 32, residual=False).
                         conv2d_mod(5, 32, residual=False).
                         custom_deconv2d([0] + [28,28,16], k_h=5, k_w=5).
                         conv2d_mod(5, 16, residual=False).
                         conv2d_mod(5, 16, residual=False).
                         conv2d_mod(5, 1, activation_fn=None).
                         flatten()
                         )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "small_res":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(activation_fn=tf.nn.elu, custom_phase=UnboundVariable('custom_phase'), wnorm=self.wnorm):
                    self.encoder_template = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape)).
                         conv2d_mod(5, 16, ).
                         conv2d_mod(5, 16, residual=True).
                         conv2d_mod(5, 16, residual=True).
                         conv2d_mod(5, 32, stride=2). # out 32*14*14
                         conv2d_mod(5, 32, residual=True).
                         conv2d_mod(5, 32, residual=True).
                         conv2d_mod(5, 32, stride=2). # out 32*7*7
                         conv2d_mod(5, 32, residual=True).
                         conv2d_mod(5, 32, residual=True).
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    self.decoder_template = \
                        (pt.template('input', self.book).
                         wnorm_fc(450, ).
                         wnorm_fc(1568, ).
                         # fully_connected(450, ).
                         # fully_connected(1568, ).
                         reshape([-1, 7, 7, 32]).
                         # reshape([self.batch_size, 1, 1, 450]).
                         # custom_deconv2d([0] + [7,7,32], k_h=1, k_w=1).
                         conv2d_mod(5, 32, residual=True).
                         conv2d_mod(5, 32, residual=True).
                         custom_deconv2d([0] + [14,14,32], k_h=5, k_w=5).
                         conv2d_mod(5, 32, residual=True).
                         conv2d_mod(5, 32, residual=True).
                         custom_deconv2d([0] + [28,28,16], k_h=5, k_w=5).
                         conv2d_mod(5, 16, residual=True).
                         conv2d_mod(5, 16, residual=True).
                         conv2d_mod(5, 1, activation_fn=None).
                         flatten()
                         )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "small_res_small_kern":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(activation_fn=tf.nn.elu, custom_phase=UnboundVariable('custom_phase'), wnorm=self.wnorm):
                    self.encoder_template = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape)).
                         conv2d_mod(3, 16, ).
                         conv2d_mod(3, 16, residual=True).
                         conv2d_mod(3, 16, residual=True).
                         conv2d_mod(3, 32, stride=2). # out 32*14*14
                         conv2d_mod(3, 32, residual=True).
                         conv2d_mod(3, 32, residual=True).
                         conv2d_mod(3, 32, stride=2). # out 32*7*7
                         conv2d_mod(3, 32, residual=True).
                         conv2d_mod(3, 32, residual=True).
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    self.decoder_template = \
                        (pt.template('input', self.book).
                         wnorm_fc(450, ).
                         wnorm_fc(1568, ).
                         # fully_connected(450, ).
                         # fully_connected(1568, ).
                         reshape([-1, 7, 7, 32]).
                         # reshape([self.batch_size, 1, 1, 450]).
                         # custom_deconv2d([0] + [7,7,32], k_h=1, k_w=1).
                         conv2d_mod(3, 32, residual=True).
                         conv2d_mod(3, 32, residual=True).
                         custom_deconv2d([0] + [14,14,32], k_h=5, k_w=5).
                         conv2d_mod(3, 32, residual=True).
                         conv2d_mod(3, 32, residual=True).
                         custom_deconv2d([0] + [28,28,16], k_h=5, k_w=5).
                         conv2d_mod(3, 16, residual=True).
                         conv2d_mod(3, 16, residual=True).
                         conv2d_mod(3, 1, activation_fn=None).
                         flatten()
                         )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(activation_fn=tf.nn.elu, custom_phase=UnboundVariable('custom_phase'), wnorm=self.wnorm):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([self.batch_size] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1, gruconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                         wnorm_fc(450, ).
                         wnorm_fc(512, ).
                         reshape([self.batch_size, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[7,7])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[14,14])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[28,28])
                    self.decoder_template = (
                        decoder.
                        conv2d_mod(3, 1, activation_fn=None).
                        flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450, ).
                               wnorm_fc(512, ).
                               reshape([-1, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[7,7])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[14,14])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[28,28])
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_gradguide":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.relu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.latent_dist.dist_flat_dim, activation_fn=None)
                         )
                    self.context_template = \
                        (pt.template("grad").
                         wnorm_fc(150, ).
                         wnorm_fc(
                            self.inference_dist.dist_flat_dim-self.latent_dist.dist_flat_dim,
                            activation_fn=None
                        )
                    )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450, ).
                               wnorm_fc(512, ).
                               reshape([-1, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[7,7])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[14,14])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[28,28])
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_widegen":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    dec_fs = network_args.get("dec_fs", 5)
                    dec_context = network_args.get("dec_context", False)
                    dec_init_size = network_args.get("dec_init_size", 4)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder_inp = pt.template('input', self.book)
                    decoder = (decoder_inp.
                               wnorm_fc(128, ).
                               reshape([
                                    -1,
                                    dec_init_size,
                                    dec_init_size,
                                    128 / dec_init_size / dec_init_size
                                ])
                               )
                    decoder = decoder.apply(tf.image.resize_nearest_neighbor, [4,4])
                    decoder = resdeconv_v1(decoder, 3, base_filters, out_wh=[7,7], nn=False, )
                    if dec_context:
                        context = decoder_inp.wnorm_fc(7*7).reshape([-1,7,7,1])
                        context2 = context.apply(tf.image.resize_nearest_neighbor, [14,14])
                        context3 = context.apply(tf.image.resize_nearest_neighbor, [28,28])
                    else:
                        context = context2 = context3 = None
                    decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[14,14], nn=True, context=context)
                    decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[28,28], nn=True, context=context2)
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                dec_fs,
                                base_filters,
                                stride=1,
                                context=context3,
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "res_encoder_gru_decoder":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    dec_fs = network_args.get("dec_fs", 5)
                    dec_init_size = network_args.get("dec_init_size", 4)
                    dec_res = network_args.get("dec_res", True)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1, gruconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder_inp = pt.template('input', self.book)
                    decoder = (decoder_inp.
                        wnorm_fc(128, ).
                        reshape([
                        -1,
                        dec_init_size,
                        dec_init_size,
                        128 / dec_init_size / dec_init_size
                    ])
                    )
                    decoder = decoder.apply(tf.image.resize_nearest_neighbor, [4,4])
                    if dec_res:
                        decoder = resdeconv_v1(decoder, 3, base_filters, out_wh=[7,7], nn=False, )
                        context = context2 = context3 = None
                        decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[14,14], nn=True, context=context)
                        decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[28,28], nn=True, context=context2)
                    else:
                        decoder = resconv_v1(decoder, 3, base_filters, nn=True)
                        decoder = decoder.apply(tf.image.resize_nearest_neighbor, [28,28])
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="gru"
                        ):
                            decoder = gruconv_v1(
                                decoder,
                                dec_fs,
                                base_filters,
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "res_encoder_plstm_drawy":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    dec_fs = network_args.get("dec_fs", 5)
                    dec_init_size = network_args.get("dec_init_size", 4)
                    dec_res = network_args.get("dec_res", True)
                    dec_ac = network_args.get("dec_ac", 1.)
                    dec_ac_exp = network_args.get("dec_ac_exp", 1.)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1,plstmconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder_inp = pt.template('input', self.book)
                    decoder = (decoder_inp.
                        wnorm_fc(128, ).
                        reshape([
                        -1,
                        dec_init_size,
                        dec_init_size,
                        128 / dec_init_size / dec_init_size
                    ])
                    )
                    decoder = decoder.apply(tf.image.resize_nearest_neighbor, [4,4])
                    if dec_res:
                        decoder = resdeconv_v1(decoder, 3, base_filters, out_wh=[7,7], nn=False, )
                        context = context2 = context3 = None
                        decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[14,14], nn=True, context=context)
                    else:
                        decoder = resconv_v1(decoder, 3, base_filters, nn=True)
                        decoder = decoder.apply(tf.image.resize_nearest_neighbor, [14,14])

                    canvas = tf.constant(np.zeros([1,28,28,1], dtype='float32'))
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="plstm"
                        ):
                            add = decoder.nl(activation_fn=tf.nn.tanh). \
                                custom_deconv2d(
                                [0, 28, 28, 1], k_h=5, k_w=5, prefix="step_dec",
                                activation_fn=None,
                            )
                            canvas = add*dec_ac + canvas
                            dec_ac *= dec_ac_exp
                            rnn_inp = canvas. \
                                conv2d_mod(5, base_filters, stride=2, prefix="step_enc")
                            decoder, _ = plstmconv_v1(
                                decoder,
                                rnn_inp,
                                dec_fs,
                                base_filters,
                            )
                    self.decoder_template = (
                        canvas.flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "res_encoder_cgru_drawy":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    dec_fs = network_args.get("dec_fs", 5)
                    dec_init_size = network_args.get("dec_init_size", 4)
                    dec_res = network_args.get("dec_res", True)
                    dec_ac = network_args.get("dec_ac", 1.)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1, gruconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder_inp = pt.template('input', self.book)
                    decoder = (decoder_inp.
                        wnorm_fc(128, ).
                        reshape([
                        -1,
                        dec_init_size,
                        dec_init_size,
                        128 / dec_init_size / dec_init_size
                    ])
                    )
                    decoder = decoder.apply(tf.image.resize_nearest_neighbor, [4,4])
                    if dec_res:
                        decoder = resdeconv_v1(decoder, 3, base_filters, out_wh=[7,7], nn=False, )
                        context = context2 = context3 = None
                        decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[14,14], nn=True, context=context)
                    else:
                        decoder = resconv_v1(decoder, 3, base_filters, nn=True)
                        decoder = decoder.apply(tf.image.resize_nearest_neighbor, [14,14])

                    canvas = tf.constant(np.zeros([1,28,28,1], dtype='float32'))
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="gru"
                        ):
                            add = decoder. \
                                custom_deconv2d(
                                    [0, 28, 28, 1], k_h=5, k_w=5, prefix="step_dec",
                                    activation_fn=None,
                                )
                            canvas = add*dec_ac + canvas
                            rnn_inp = canvas.\
                                conv2d_mod(5, base_filters, stride=2, prefix="step_enc")
                            decoder = gruconv_v1(
                                decoder,
                                dec_fs,
                                base_filters,
                                inp=rnn_inp,
                            )
                    self.decoder_template = (
                            canvas.flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_widegen_sa":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    dec_fs = network_args.get("dec_fs", 5)
                    dec_context = network_args.get("dec_context", False)
                    dec_init_size = network_args.get("dec_init_size", 4)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder_inp = pt.template('input', self.book)
                    zdim = self.latent_dist.dim
                    decoder = (decoder_inp.
                        reshape([
                        -1,
                        dec_init_size,
                        dec_init_size,
                        zdim / dec_init_size / dec_init_size
                    ])
                    )
                    decoder = decoder.apply(tf.image.resize_nearest_neighbor, [4,4])
                    decoder = resdeconv_v1(decoder, 3, base_filters, out_wh=[7,7], nn=False, )
                    if dec_context:
                        context = decoder_inp.wnorm_fc(7*7).reshape([-1,7,7,1])
                        context2 = context.apply(tf.image.resize_nearest_neighbor, [14,14])
                        context3 = context.apply(tf.image.resize_nearest_neighbor, [28,28])
                    else:
                        context = context2 = context3 = None
                    decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[14,14], nn=True, context=context)
                    decoder = resdeconv_v1(decoder, dec_fs, base_filters, out_wh=[28,28], nn=True, context=context2)
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                dec_fs,
                                base_filters,
                                stride=1,
                                context=context3,
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_widegen_allshare":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", True)
                    enc_rep = network_args.get("enc_rep", 1)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template.\
                         wnorm_fc(450, )
                    self.encoder_template = self.encoder_template.\
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(128, ).
                               reshape([-1, 4, 4, 8])
                               )
                    decoder = decoder.\
                        apply(tf.image.resize_nearest_neighbor, [28, 28])
                    decoder = resconv_v1(decoder, 3, base_filters, stride=1, nn=True)
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                3,
                                base_filters,
                                stride=1,
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_widegen_min":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    steps = network_args["steps"]
                    base_filters = network_args["base_filters"]
                    enc_fc = network_args.get("enc_fc", False)
                    enc_rep = network_args.get("enc_rep", 0)
                    enc_keep = network_args.get("enc_keep", 1.)
                    enc_nn = network_args.get("enc_nn", True)
                    print(network_args)
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2, nn=enc_nn, keep_prob=enc_keep) #14
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 16, stride=1, keep_prob=enc_keep)
                    encoder = resconv_v1(encoder, 3, 32, stride=2, nn=enc_nn, keep_prob=enc_keep) #7
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1, keep_prob=enc_keep)
                    encoder = resconv_v1(encoder, 3, 32, stride=2, nn=enc_nn, keep_prob=enc_keep) #4
                    for _ in xrange(enc_rep):
                        encoder = resconv_v1(encoder, 3, 32, stride=1, keep_prob=enc_keep)
                    self.encoder_template = \
                        (encoder.
                         flatten())
                    if enc_fc:
                        self.encoder_template = self.encoder_template. \
                            wnorm_fc(450, )
                    self.encoder_template = self.encoder_template. \
                        wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                    decoder = (pt.template('input', self.book).
                               reshape([-1, 2, 2, self.latent_dist.dim / 4])
                               )
                    decoder = resconv_v1(decoder, 2, base_filters, stride=1, nn=True)
                    decoder = decoder. \
                        apply(tf.image.resize_nearest_neighbor, [7, 7])
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                5,
                                base_filters,
                                stride=1,
                            )
                    decoder = decoder. \
                        apply(tf.image.resize_nearest_neighbor, [14, 14])
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                5,
                                base_filters,
                                stride=1,
                            )
                    decoder = decoder. \
                        apply(tf.image.resize_nearest_neighbor, [28, 28])
                    for _ in xrange(steps):
                        with pt.defaults_scope(
                                var_scope="wide_gen"
                        ):
                            decoder = resconv_v1(
                                decoder,
                                5,
                                base_filters,
                                stride=1,
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_half_filters":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 8, stride=2) #14
                    encoder = resconv_v1(encoder, 3, 8, stride=1)
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #7
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450/2, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450/2, ).
                               wnorm_fc(512/2, ).
                               reshape([-1, 4, 4, 32/2])
                               )
                    decoder = resconv_v1(decoder, 3, 16, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[7,7])
                    decoder = resconv_v1(decoder, 3, 16, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[14,14])
                    decoder = resconv_v1(decoder, 3, 16, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 8, out_wh=[28,28])
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(3, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_filters_ratio":
                from prettytensor import UnboundVariable
                model_avg = network_args.get("model_avg", False)
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                        model_avg=model_avg,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    gen_base_filters = network_args.get("base_filters", 16)
                    gen_fc_size = network_args.get("fc_size", 450)
                    ac = network_args.get("ac", 0.1)
                    fs = network_args.get("filter_size", 3)

                    base_filters = network_args.get("enc_base_filters", gen_base_filters)
                    fc_size = network_args.get("enc_fc_size", gen_fc_size)
                    fc_keep_prob = network_args.get("enc_fc_keep_prob", 1.)
                    res_keep_prob = network_args.get("enc_res_keep_prob", 1.)
                    nn = network_args.get("enc_nn", False)
                    rep = network_args.get("enc_rep", 1)
                    print("encoder nn %s" % nn)
                    print("encoder fs %s" % fs)
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters,
                        stride=2,
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    ) #14
                    for _ in xrange(rep):
                       encoder = resconv_v1(encoder, fs, base_filters, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters*2,
                        stride=2,
                        keep_prob=res_keep_prob,
                        add_coeff=ac
                    ) #7
                    for _ in xrange(rep):
                        encoder = resconv_v1(encoder, fs, base_filters*2, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters*2,
                        stride=2,
                        keep_prob=res_keep_prob,
                        add_coeff=ac
                    ) #4
                    for _ in xrange(rep):
                        encoder = resconv_v1(encoder, fs, base_filters*2, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    self.encoder_template = \
                        (encoder.
                         flatten(). # 4*4*base_filters*2 \approx 512
                         wnorm_fc(fc_size, ).dropout(fc_keep_prob).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    base_filters = network_args.get("dec_base_filters", gen_base_filters)
                    fc_size = network_args.get("dec_fc_size", gen_fc_size)
                    fc_keep_prob = network_args.get("dec_fc_keep_prob", 1.)
                    res_keep_prob = network_args.get("dec_res_keep_prob", 1.)
                    nn = network_args.get("dec_nn", False)
                    rep = network_args.get("dec_rep", 1)
                    print("decoder nn %s" % nn)
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(fc_size, ).dropout(fc_keep_prob).
                               wnorm_fc(4*4*(base_filters*2), ).dropout(fc_keep_prob).
                               reshape([-1, 4, 4, base_filters*2])
                               )
                    for _ in xrange(rep):
                        decoder = resconv_v1(decoder, fs, base_filters*2, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters*2,
                        out_wh=[7,7],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep):
                        decoder = resconv_v1(decoder, fs, base_filters*2, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters*2,
                        out_wh=[14,14],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep):
                        decoder = resconv_v1(decoder, fs, base_filters*2, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters,
                        out_wh=[28,28],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep-1):
                        decoder = resconv_v1(decoder, fs, base_filters, stride=1, keep_prob=res_keep_prob, add_coeff=ac)
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(fs, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "res_nofc":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    base_filters = network_args["base_filters"]# , None)
                    ac = network_args["ac"]#, None)
                    fs = network_args["filter_size"]#, None)
                    tie_weights = network_args.get("tie_weights", False)
                    print("tie weights %s" % tie_weights)

                    res_keep_prob = network_args["enc_res_keep_prob"]#, None)
                    nn = network_args["enc_nn"]#, None)
                    rep = network_args["enc_rep"]#, None)
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters,
                        stride=2,
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    ) #14
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                            var_scope="res_1" if tie_weights else None
                        ):
                            encoder = resconv_v1(
                                encoder,
                                fs,
                                base_filters,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters*2,
                        stride=2,
                        keep_prob=res_keep_prob,
                        add_coeff=ac
                    ) #7
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                                var_scope="res_2" if tie_weights else None
                        ):
                            encoder = resconv_v1(
                                encoder,
                                fs,
                                base_filters*2,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    encoder = resconv_v1(
                        encoder,
                        fs,
                        base_filters*2,
                        stride=2,
                        keep_prob=res_keep_prob,
                        add_coeff=ac
                    ) #4
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                                var_scope="res_3" if tie_weights else None
                        ):
                            encoder = resconv_v1(
                                encoder,
                                fs,
                                base_filters*2,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    qz_dim = self.inference_dist.dist_flat_dim
                    pz_dim = self.latent_dist.dim
                    self.encoder_template = \
                        (encoder.
                         conv2d_mod(fs, qz_dim, activation_fn=None).
                         apply(tf.reduce_mean, [1,2])
                         )
                    res_keep_prob = network_args["dec_res_keep_prob"]#, None)
                    nn = network_args["dec_nn"]#, None)
                    rep = network_args["dec_rep"]#, None)
                    print("decoder nn %s" % nn)
                    decoder = (pt.template('input', self.book).
                               reshape([-1, 1, 1, pz_dim]).
                               apply(tf.tile, [1,4,4,1]).
                               conv2d_mod(fs, base_filters*2)
                               )
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                                var_scope="de_res_1" if tie_weights else None
                        ):
                            decoder = resconv_v1(
                                decoder,
                                fs,
                                base_filters*2,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters*2,
                        out_wh=[7,7],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                                var_scope="de_res_2" if tie_weights else None
                        ):
                            decoder = resconv_v1(
                                decoder,
                                fs,
                                base_filters*2,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters*2,
                        out_wh=[14,14],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep):
                        with pt.defaults_scope(
                                var_scope="de_res_3" if tie_weights else None
                        ):
                            decoder = resconv_v1(
                                decoder,
                                fs,
                                base_filters*2,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    decoder = resdeconv_v1(
                        decoder,
                        fs,
                        base_filters,
                        out_wh=[28,28],
                        keep_prob=res_keep_prob,
                        nn=nn,
                        add_coeff=ac
                    )
                    for _ in xrange(rep-1):
                        with pt.defaults_scope(
                                var_scope="de_res_4" if tie_weights else None
                        ):
                            decoder = resconv_v1(
                                decoder,
                                fs,
                                base_filters,
                                stride=1,
                                keep_prob=res_keep_prob,
                                add_coeff=ac
                            )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(fs, 1, activation_fn=None).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_cifar":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 5, 16, stride=2) #16
                    encoder = resconv_v1(encoder, 5, 16, stride=1)
                    encoder = resconv_v1(encoder, 5, 32, stride=2) #8
                    encoder = resconv_v1(encoder, 5, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450, ).
                               wnorm_fc(512, ).
                               reshape([-1, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[8,8])
                    decoder = resconv_v1(decoder, 5, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 5, 32, out_wh=[16,16])
                    decoder = resconv_v1(decoder, 5, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 5, 16, out_wh=[32,32])
                    decoder = resconv_v1(decoder, 5, 16, stride=1)
                    if isinstance(self.output_dist, Mixture):
                        modes = self.output_dist.modes
                    else:
                        modes = 1
                    # modes have diff scale params
                    scale_var = tf.Variable(
                        initial_value=np.zeros([1,modes,3,1,1], dtype='float32'),
                        name="channel_scale"
                    )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(
                            5,
                            3*modes,
                            activation_fn=None
                        ).
                        apply(tf.transpose, [0, 3, 1, 2]).
                        reshape([-1, modes, 3, 32, 32]).
                        apply(lambda conv:
                                tf.concat(
                                    2,
                                    [
                                        tf.clip_by_value(
                                            conv,
                                            -0.5 + 1 / 512.,
                                            0.5 - 1 / 512.
                                        ),
                                        conv*0. + scale_var
                                    ]
                                )
                        ).
                        reshape([-1, modes, 2, 3, 32, 32]).
                        apply(tf.transpose, [0, 1, 2, 4, 5, 3]).
                        flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_cifar_spatial_scale":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 3, 16, stride=2) #16
                    encoder = resconv_v1(encoder, 3, 16, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #8
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450, ).
                               wnorm_fc(512, ).
                               reshape([-1, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[8,8])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[16,16])
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 16, out_wh=[32,32])
                    scale_var = tf.Variable(
                        initial_value=np.zeros([1,32,32,1], dtype='float32'),
                        name="spatial_scale"
                    )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(
                            3,
                            3,
                            activation_fn=None
                        ).
                            apply(
                            lambda conv:
                            tf.concat(3, [conv, conv*0. + scale_var])
                        ).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "resv1_k3_pixel_bias_cifar_pred_scale":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                        wnorm=self.wnorm,
                        pixel_bias=True,
                ):
                    encoder = \
                        (pt.template('input', self.book).
                         reshape([-1] + list(image_shape))
                         )
                    from sandbox.pchen.InfoGAN.infogan.misc.custom_ops import resconv_v1, resdeconv_v1
                    encoder = resconv_v1(encoder, 5, 16, stride=2) #16
                    encoder = resconv_v1(encoder, 5, 16, stride=1)
                    encoder = resconv_v1(encoder, 5, 32, stride=2) #8
                    encoder = resconv_v1(encoder, 5, 32, stride=1)
                    encoder = resconv_v1(encoder, 3, 32, stride=2) #4
                    encoder = resconv_v1(encoder, 3, 32, stride=1)
                    self.encoder_template = \
                        (encoder.
                         flatten().
                         wnorm_fc(450, ).
                         wnorm_fc(self.inference_dist.dist_flat_dim, activation_fn=None)
                         )
                    decoder = (pt.template('input', self.book).
                               wnorm_fc(450, ).
                               wnorm_fc(512, ).
                               reshape([-1, 4, 4, 32])
                               )
                    decoder = resconv_v1(decoder, 3, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 3, 32, out_wh=[8,8])
                    decoder = resconv_v1(decoder, 5, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 5, 32, out_wh=[16,16])
                    decoder = resconv_v1(decoder, 5, 32, stride=1)
                    decoder = resdeconv_v1(decoder, 5, 16, out_wh=[32,32])
                    # scale_var = tf.Variable(
                    #     initial_value=np.zeros([1,32,32,1], dtype='float32'),
                    #     name="spatial_scale"
                    # )
                    self.decoder_template = (
                        decoder.
                            conv2d_mod(
                            3,
                            3*2,
                            activation_fn=None
                        ).
                        flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            elif self.network_type == "small_conv":
                from prettytensor import UnboundVariable
                keep_prob = network_args["keep_prob"]
                with pt.defaults_scope(
                        activation_fn=tf.nn.elu,
                        custom_phase=UnboundVariable('custom_phase'),
                ):
                    self.encoder_template = \
                        (pt.template('input').
                         reshape([-1] + list(image_shape)).
                         conv2d_mod(5, 32, stride=2).custom_dropout(keep_prob).
                         conv2d_mod(5, 64, stride=2).custom_dropout(keep_prob).
                         conv2d_mod(5, 64, stride=2).custom_dropout(keep_prob).
                         flatten().
                         fully_connected(self.latent_dist.dist_flat_dim, activation_fn=None))
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([-1] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
                    self.decoder_template = \
                        (pt.template('input').
                         fully_connected(7*7*2).reshape([-1, 7, 7, 2]).
                         custom_deconv2d([0, 14, 14, 16], ).dropout(keep_prob).
                         custom_deconv2d([0, 28, 28, 1], activation_fn=None).
                         flatten())
            elif self.network_type == "cifar_id":
                from prettytensor import UnboundVariable
                with pt.defaults_scope(
                ):
                    encoder = \
                        (pt.template('input', self.book)
                         )
                    self.encoder_template = \
                        (encoder.
                         apply(lambda x: tf.concat(
                            1,
                            [x, x*0 - 100000.]
                        ))
                    )
                    decoder = (pt.template('input', self.book).
                               reshape([-1, 32, 32, 3])
                               )
                    if isinstance(self.output_dist, Mixture):
                        modes = self.output_dist.modes
                        assert False
                    else:
                        modes = 1
                    # modes have diff scale params
                    scale_var = tf.Variable(
                        initial_value=np.zeros([1,modes * 3,1,1], dtype='float32'),
                        name="channel_scale"
                    )
                    global count
                    count = 0
                    def hehe(x):
                        global count
                        count += 1
                        tf.image_summary("hehe%s"%count, x)
                        return x


                    self.decoder_template = (
                        decoder.
                            apply(hehe).
                            apply(tf.transpose, [0, 3, 1, 2]).
                            reshape([-1, modes*3, 32, 32]).
                            apply(lambda conv:
                                  tf.concat(
                                      1,
                                      [
                                          tf.clip_by_value(
                                              conv + 1./512,
                                              -0.5 + 1 / 512.,
                                              0.5 - 1 / 512.
                                          ),
                                          conv*0. + scale_var,
                                      ]
                                  ),
                                  ).
                            reshape([-1, 2, 3, 32, 32]).
                            apply(tf.transpose, [0, 1,3,4,2]).
                            flatten()
                    )
                    self.reg_encoder_template = \
                        (pt.template('input').
                         reshape([self.batch_size] + list(image_shape)).
                         custom_conv2d(5, 32, ).
                         custom_conv2d(5, 64, ).
                         custom_conv2d(5, 128, edges='VALID').
                         # dropout(0.9).
                         flatten().
                         fully_connected(self.reg_latent_dist.dist_flat_dim, activation_fn=None))
            else:
                raise NotImplementedError

    def init_mode(self):
        self.output_dist.init_mode()
        self.latent_dist.init_mode()
        self.inference_dist.init_mode()
        self.reg_latent_dist.init_mode()
        self.nonreg_latent_dist.init_mode()
        self.custom_phase = CustomPhase.init
        if self.book.summary_collections:
            self.book_summary_collections = self.book.summary_collections
            self.book.summary_collections = None

    def train_mode(self, eval=False):
        self.output_dist.train_mode()
        self.latent_dist.train_mode()
        self.inference_dist.train_mode()
        self.reg_latent_dist.train_mode()
        self.nonreg_latent_dist.train_mode()
        if eval:
            self.custom_phase = CustomPhase.test
        else:
            self.custom_phase = CustomPhase.train
        self.book.summary_collections = self.book_summary_collections

    def encode(self, x_var, k=1):
        if "gradguide" in self.network_type:
            return self.encode_gradguide(x_var, k=k)
        args = dict(
            input=x_var, custom_phase=self.custom_phase
        )
        try:
            z_dist_flat = self.encoder_template.construct(**args).tensor
        except ValueError as e:
            if "custom_phase" not in e.message:
                raise e
            args = dict(
                input=x_var,
            )
            z_dist_flat = self.encoder_template.construct(**args).tensor
        if k != 1:
            z_dist_flat = tf.reshape(
                tf.tile(z_dist_flat, [1, k]),
                [-1, self.inference_dist.dist_flat_dim],
            )
        z_dist_info = self.inference_dist.activate_dist(z_dist_flat)
        return self.inference_dist.sample_logli(z_dist_info) \
               + (z_dist_info,)

    def encode_gradguide(self, x_var, k=1):
        assert k==1
        args = dict(
            input=x_var, custom_phase=self.custom_phase
        )
        try:
            z_dist_flat = self.encoder_template.construct(**args).tensor
        except ValueError as e:
            if "custom_phase" not in e.message:
                raise e
            args = dict(
                input=x_var,
            )
            z_dist_flat = self.encoder_template.construct(**args).tensor
        zdim = self.latent_dist.dim
        qz_mean = z_dist_flat[:, zdim:]
        log_p_x_given_z = self.output_dist.logli(
            x_var,
            self.decode(qz_mean)[1]
        )
        grad_z_mean = tf.reshape(tf.gradients(log_p_x_given_z, qz_mean), [-1, zdim])
        # grad_z_mean = tf.stop_gradient(grad_z_mean)
        # grad_z_mean = tf.nn.sigmoid(grad_z_mean) # seems important for stability reason
        context = self.context_template.construct(grad=grad_z_mean, custom_phase=self.custom_phase).tensor
        # context = tf.stop_gradient(context)
        z_dist_flat_aug = tf.concat(
            1,
            [
                context,
                z_dist_flat,
            ])
        z_dist_info = self.inference_dist.activate_dist(z_dist_flat_aug)
        return self.inference_dist.sample_logli(z_dist_info) \
               + (z_dist_info,)

    def reg_encode(self, x_var):
        reg_z_dist_flat = self.reg_encoder_template.construct(input=x_var, ).tensor
        reg_z_dist_info = self.reg_latent_dist.activate_dist(reg_z_dist_flat)
        return self.reg_latent_dist.sample(reg_z_dist_info), reg_z_dist_info

    def decode(self, z_var):
        args = dict(
            input=z_var, custom_phase=self.custom_phase
        )
        try:
            x_dist_flat = self.decoder_template.construct(**args).tensor
        except ValueError as e:
            print(e)
            args = dict(
                input=z_var,
            )
            x_dist_flat = self.decoder_template.construct(**args).tensor
        # x_dist_flat = self.decoder_template.construct(input=z_var, custom_phase=self.custom_phase).tensor
        x_dist_info = self.output_dist.activate_dist(x_dist_flat)
        return self.output_dist.sample(x_dist_info), x_dist_info

    def reg_z(self, z_var):
        ret = []
        for (_, reg_i), z_i in zip(self.latent_spec, self.latent_dist.split_var(z_var)):
            if reg_i:
                ret.append(z_i)
        return self.reg_latent_dist.join_vars(ret)

    def nonreg_z(self, z_var):
        ret = []
        for (_, reg_i), z_i in zip(self.latent_spec, self.latent_dist.split_var(z_var)):
            if not reg_i:
                ret.append(z_i)
        return self.nonreg_latent_dist.join_vars(ret)

    def reg_dist_info(self, dist_info):
        ret = []
        for (_, reg_i), dist_info_i in zip(self.latent_spec, self.latent_dist.split_dist_info(dist_info)):
            if reg_i:
                ret.append(dist_info_i)
        return self.reg_latent_dist.join_dist_infos(ret)

    def nonreg_dist_info(self, dist_info):
        ret = []
        for (_, reg_i), dist_info_i in zip(self.latent_spec, self.latent_dist.split_dist_info(dist_info)):
            if not reg_i:
                ret.append(dist_info_i)
        return self.nonreg_latent_dist.join_dist_infos(ret)

    def combine_reg_nonreg_z(self, reg_z_var, nonreg_z_var):
        reg_z_vars = self.reg_latent_dist.split_var(reg_z_var)
        reg_idx = 0
        nonreg_z_vars = self.nonreg_latent_dist.split_var(nonreg_z_var)
        nonreg_idx = 0
        ret = []
        for idx, (dist_i, reg_i) in enumerate(self.latent_spec):
            if reg_i:
                ret.append(reg_z_vars[reg_idx])
                reg_idx += 1
            else:
                ret.append(nonreg_z_vars[nonreg_idx])
                nonreg_idx += 1
        return self.latent_dist.join_vars(ret)

    def combine_reg_nonreg_dist_info(self, reg_dist_info, nonreg_dist_info):
        reg_dist_infos = self.reg_latent_dist.split_dist_info(reg_dist_info)
        reg_idx = 0
        nonreg_dist_infos = self.nonreg_latent_dist.split_dist_info(nonreg_dist_info)
        nonreg_idx = 0
        ret = []
        for idx, (dist_i, reg_i) in enumerate(self.latent_spec):
            if reg_i:
                ret.append(reg_dist_infos[reg_idx])
                reg_idx += 1
            else:
                ret.append(nonreg_dist_infos[nonreg_idx])
                nonreg_idx += 1
        return self.latent_dist.join_dist_infos(ret)
