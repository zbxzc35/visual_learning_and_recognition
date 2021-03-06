from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Imports
import os
import sys
import numpy as np
import tensorflow as tf
import argparse
import os.path as osp
from PIL import Image
from functools import partial

from eval import compute_map
#import models
from tensorflow.core.framework import summary_pb2

tf.logging.set_verbosity(tf.logging.INFO)


CLASS_NAMES = [
    'aeroplane',
    'bicycle',
    'bird',
    'boat',
    'bottle',
    'bus',
    'car',
    'cat',
    'chair',
    'cow',
    'diningtable',
    'dog',
    'horse',
    'motorbike',
    'person',
    'pottedplant',
    'sheep',
    'sofa',
    'train',
    'tvmonitor',
]

num_classes = 20

def cnn_model_fn(features, labels, mode, num_classes=20):
    # Write this function
    input_layer = tf.reshape(features["x"], [-1, 256, 256, 3])

    # Convolutional Layer #1
    conv1 = tf.layers.conv2d(
        inputs=input_layer,
        filters=32,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)

    # Pooling Layer #1
    pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2, 2], strides=2)  #(28-2)/2 = 13x13

    # Convolutional Layer #2 and Pooling Layer #2
    conv2 = tf.layers.conv2d(
        inputs=pool1,
        filters=64,
        kernel_size=[5, 5],
        padding="same",
        activation=tf.nn.relu)
    pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[2, 2], strides=2)  #(13-2)/2: 7x7x64

    # Dense Layer
    pool2_flat = tf.reshape(pool2, [-1, 64 * 64 * 64])
    dense = tf.layers.dense(inputs=pool2_flat, units=1024,
                            activation=tf.nn.relu)
    dropout = tf.layers.dropout(
        inputs=dense, rate=0.4, training=mode == tf.estimator.ModeKeys.TRAIN)

    # Logits Layer
    #print dropout.shape
    logits = tf.layers.dense(inputs=dropout, units=num_classes)
    probs = tf.sigmoid(logits, name="sigmoid_tensor")
    pred_float = tf.greater_equal(probs, 0.5)
    pred_int = tf.cast(pred_float, dtype="int32")

    predictions = {
        # Generate predictions (for PREDICT and EVAL mode)
        "classes": pred_int,
        # Add `softmax_tensor` to the graph. It is used for PREDICT and by the
        # `logging_hook`.
        #
        "probabilities": probs
    }

    if mode == tf.estimator.ModeKeys.PREDICT:
        return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

    # Calculate Loss (for both TRAIN and EVAL modes)
#    onehot_labels = tf.one_hot(indices=tf.cast(labels, tf.int32), depth=10)
    loss = tf.identity(tf.losses.sigmoid_cross_entropy(
         multi_class_labels=labels, logits=logits), name='loss')

    # Configure the Training Op (for TRAIN mode)
    if mode == tf.estimator.ModeKeys.TRAIN:
        optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.001)
        train_op = optimizer.minimize(
            loss=loss,
            global_step=tf.train.get_global_step())
        return tf.estimator.EstimatorSpec(
            mode=mode, loss=loss, train_op=train_op)

    # Add evaluation metrics (for EVAL mode)
    eval_metric_ops = {
        "accuracy": tf.metrics.accuracy(
            labels=labels, predictions=predictions["classes"])}

    #logging_hook = tf.train.LoggingTensorHook({"loss": loss}, every_n_iter=200)

    # in main logging: histograms: tf.summary, summary_saver
    return tf.estimator.EstimatorSpec(
        mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)


def load_pascal(data_dir, split='train'):
    """
    Function to read images from PASCAL data folder.
    Args:
        data_dir (str): Path to the VOC2007 directory.
        split (str): train/val/trainval split to use.
    Returns:
        images (np.ndarray): Return a np.float32 array of
            shape (N, H, W, 3), where H, W are 224px each,
            and each image is in RGB format.
        labels (np.ndarray): An array of shape (N, 20) of
            type np.int32, with 0s and 1s; 1s for classes that
            are active in that image.
        weights: (np.ndarray): An array of shape (N, 20) of
            type np.int32, with 0s and 1s; 1s for classes that
            are confidently labeled and 0s for classes that
            are ambiguous.
    """
    # Wrote this function
    H = 256
    W = 256

    N_dict = {'train': 2501, 'val':2510, 'trainval': 5011, 'test': 4952}
    N = N_dict[split]

    images = np.zeros((N, H, W, 3), dtype=np.float32)
    labels = np.zeros((N, num_classes), dtype=np.int32)
    weights = np.zeros((N, num_classes), dtype=np.int32)

    #Load Images
    file_name = data_dir + "ImageSets/Main/" + split + '.txt'
    with open(file_name, 'r') as image_lst_file:
        i=0
        for line in image_lst_file.readlines():
            img_no = line.strip('\n')
            image_name = data_dir + 'JPEGImages/' + img_no + '.jpg'
            img = Image.open(image_name)
            img = img.resize((H, W), Image.ANTIALIAS)
            imgarr = np.asarray(img, dtype=np.float32)
            images[i, :, :, :] = imgarr
            i += 1

    for i in range(len(CLASS_NAMES)):
        cls = CLASS_NAMES[i]
        file_name = data_dir + "ImageSets/Main/" + cls + '_' + split + '.txt'
        with open(file_name, 'r') as image_lst_file:
            im_idx = 0
            for line in image_lst_file.readlines():
                _, is_present = line.strip('\n').split()
                is_present = int(is_present)
                if is_present == 1:
                    labels[im_idx][i] = 1

                if is_present != 0:
                    weights[im_idx][i] = 1
                im_idx += 1
    return images, labels, weights


def parse_args():
    parser = argparse.ArgumentParser(
        description='Train a classifier in tensorflow!')
    parser.add_argument(
        'data_dir', type=str, default='data/VOC2007',
        help='Path to PASCAL data storage')
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    args = parser.parse_args()
    return args


def _get_el(arr, i):
    try:
        return arr[i]
    except IndexError:
        return arr

def summary_var(log_dir, name, val, step):
    writer = tf.summary.FileWriterCache.get(log_dir)
    summary_proto = summary_pb2.Summary()
    value = summary_proto.value.add()
    value.tag = name
    value.simple_value = float(val)
    writer.add_summary(summary_proto, step)
    writer.flush()

def main():
    args = parse_args()
    # Load training and eval data
    #train_data, train_labels, train_weights = load_pascal(
    #    args.data_dir, split='trainval')
    #np.save(os.path.join(args.data_dir, 'trainval' + '_data_images'), train_data)
    #np.save(os.path.join(args.data_dir, 'trainval' + '_data_labels'), train_labels)
    #np.save(os.path.join(args.data_dir, 'trainval' + '_data_weights'), train_weights)

    train_data = np.load(os.path.join(args.data_dir, 'trainval' + '_data_images.npy'))
    train_labels = np.load(os.path.join(args.data_dir, 'trainval' + '_data_labels.npy'))
    train_weights = np.load(os.path.join(args.data_dir, 'trainval' + '_data_weights.npy'))

#    eval_data, eval_labels, eval_weights = load_pascal(
#        args.data_dir, split='test')

#    np.save(os.path.join(args.data_dir, 'test' + '_data_images'), eval_data)
#    np.save(os.path.join(args.data_dir, 'test' + '_data_labels'), eval_labels)
#    np.save(os.path.join(args.data_dir, 'test' + '_data_weights'), eval_weights)

    eval_data = np.load(os.path.join(args.data_dir, 'test' + '_data_images.npy'))
    eval_labels = np.load(os.path.join(args.data_dir, 'test' + '_data_labels.npy'))
    eval_weights = np.load(os.path.join(args.data_dir, 'test' + '_data_weights.npy'))

    # print("train_data.shape", train_data.shape)
    # print("train_lables.shape", train_labels.shape)
    # print("train_weights.shape", train_weights.shape)
    # print("eval_data.shape", eval_data.shape)
    # print("e_labels.shape", eval_labels.shape)
    # print("e_weights.shape", eval_weights.shape)


    pascal_classifier = tf.estimator.Estimator(
        model_fn=partial(cnn_model_fn,
                         num_classes=train_labels.shape[1]),
        model_dir="/tmp/01_pascal_model_scratch")

    tensors_to_log = {"loss": "loss"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=10)

    BATCH_SIZE = 10# Train the model
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data, "w": train_weights},
        y=train_labels,
        batch_size=BATCH_SIZE,
        num_epochs=None,
        shuffle=True)
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data, "w": eval_weights},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)

    BATCH_SIZE = 10
    no_of_iters = 1000
    no_of_pts = 100
    no_of_steps = no_of_iters/no_of_pts

    for i in range(no_of_pts):
        pascal_classifier.train(
            input_fn=train_input_fn,
            steps=no_of_steps,
            hooks=[logging_hook])
        # Evaluate the model and print results
        pred = list(pascal_classifier.predict(input_fn=eval_input_fn))
        pred = np.stack([p['probabilities'] for p in pred])

        rand_AP = compute_map(
            eval_labels, np.random.random(eval_labels.shape),
            eval_weights, average=None)
        print('Random AP: {} mAP'.format(np.mean(rand_AP)))

        gt_AP = compute_map(
            eval_labels, eval_labels, eval_weights, average=None)
        print('GT AP: {} mAP'.format(np.mean(gt_AP)))

        AP = compute_map(eval_labels, pred, eval_weights, average=None)
        print('Obtained {} mAP'.format(np.mean(AP)))

        summary_var(log_dir="/tmp/01_pascal_model_scratch",
                    name="mAP", val=np.mean(AP), step=i*no_of_steps)
        #print('per class:')
        #for cid, cname in enumerate(CLASS_NAMES):
        #    print('{}: {}'.format(cname, _get_el(AP, cid)))

        #value = summary_pb2.Summary.Value(tag="mAP", simple_value=np.mean(AP))
        #summary = summary_pb2.Summary(value=[value])


if __name__ == "__main__":
    main()
