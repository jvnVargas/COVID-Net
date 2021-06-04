from sklearn.metrics import confusion_matrix
import pandas as pd
import numpy as np
from tensorflow.keras import backend as K
import tensorflow as tf
import os, argparse
import cv2

from data import process_image_file
from load_data import loadDataJSRTSingle


def eval(sess, dataset, testfile, batch_size, image_tensor, pred_tensor, mapping,
        training_tensor='keras_learning_phase:0'):
    y_test = []
    pred = []
    test_dataset, count, batch_size = dataset.test_dataset(testfile, batch_size)
    data_next = test_dataset.make_one_shot_iterator().get_next()
    total_batch = int(np.ceil(count/batch_size))
    progbar = tf.keras.utils.Progbar(total_batch)

    print('Started Testing')
    for i in range(total_batch):
        # Get batch of data
        data = sess.run(data_next)
        batch_x = data['image']
        batch_sem_x = data['sem_image']
        batch_y = data['label']
        feed_dict={image_tensor: batch_x,
                   training_tensor: 0}
        
        y_test.extend(batch_y.argmax(axis=1))
        pred_values = sess.run(pred_tensor, feed_dict=feed_dict)
        pred.extend(pred_values.argmax(axis=1))
        progbar.update(i + 1)
    y_test = np.array(y_test)
    pred = np.array(pred)

    # Create confusion matrix
    print()
    matrix = confusion_matrix(y_test, pred, labels=(0,1))
    matrix = matrix.astype('float')
    print(matrix)

    # Compute accuracy, sensitivity, and PPV
    diag = np.diag(matrix)
    acc = diag.sum()/max(matrix.sum(), 1)
    sens = diag/np.maximum(matrix.sum(axis=1), 1)
    ppv = diag/np.maximum(matrix.sum(axis=0), 1)
    print('Accuracy -', '{:.3f}'.format(acc))
    print('Sens -', ', '.join('{}: {:.3f}'.format(cls.capitalize(), sens[i]) for cls, i in mapping.items()))
    print('PPV -', ', '.join('{}: {:.3f}'.format(cls.capitalize(), ppv[i]) for cls, i in mapping.items()))

    # Store results in dict
    metrics = {'sens_' + cls: sens[i] for cls, i in mapping.items()}
    metrics.update({'ppv_' + cls: ppv[i] for cls, i in mapping.items()})
    metrics['accuracy'] = acc

    return metrics