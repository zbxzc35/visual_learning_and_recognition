from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Imports
import sys
import numpy as np
import tensorflow as tf
import argparse
import os.path as osp
from PIL import Image
from functools import partial

from eval import compute_map
#import models

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
    input_layer = tf.reshape(features["x"], [-1, 28, 28, 1])

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
    onehot_labels = tf.one_hot(indices=tf.cast(labels, tf.int32), depth=10)
    loss = tf.identity(tf.losses.softmax_cross_entropy(
        onehot_labels=onehot_labels, logits=logits), name='loss')

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


def main():
    args = parse_args()
    # Load training and eval data
    train_data, train_labels, train_weights = load_pascal(
        args.data_dir, split='trainval')
    eval_data, eval_labels, eval_weights = load_pascal(
        args.data_dir, split='test')

    pascal_classifier = tf.estimator.Estimator(
        model_fn=partial(cnn_model_fn,
                         num_classes=train_labels.shape[1]),
        model_dir="/tmp/pascal_model_scratch")

    tensors_to_log = {"loss": "loss"}
    logging_hook = tf.train.LoggingTensorHook(
        tensors=tensors_to_log, every_n_iter=10)
    # Train the model
    BATCH_SIZE = 100
    NUM_ITERS = 5
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": train_data, "w": train_weights},
        y=train_labels,
        batch_size=BATCH_SIZE,
        num_epochs=None,
        shuffle=True)
    pascal_classifier.train(
        input_fn=train_input_fn,
        steps=NUM_ITERS,
        hooks=[logging_hook])
    # Evaluate the model and print results
    eval_input_fn = tf.estimator.inputs.numpy_input_fn(
        x={"x": eval_data, "w": eval_weights},
        y=eval_labels,
        num_epochs=1,
        shuffle=False)
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
    print('per class:')
    for cid, cname in enumerate(CLASS_NAMES):
        print('{}: {}'.format(cname, _get_el(AP, cid)))


if __name__ == "__main__":
    main()
