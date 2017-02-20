# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE.md file in the project root
# for full license information.
# ==============================================================================

import sys
from . import cntk_py
from .device import use_default_device
from .utils import sanitize_var_map, sanitize_function, typemap, value_to_seq
from .io import _py_dict_to_cntk_dict

__doc__ = '''\
A training session encapsulates a typical training loop and binds together a minibatch source that is used for training, a :doc:`trainer <cntk.trainer>` and an optional cross validation minibatch source. A training session takes care of consistent checkpointing and progress printing with specified frequencies. 
'''

class TrainingSession(cntk_py.TrainingSession):
    '''
    The instance of the class should be created by using :func:`~cntk.training_session.training_session` function.

    A training session trains a model using the specified ``trainer`` and the ``training_minibatch_source``
    where the minibatch size defined by ``mb_size_schedule``. The mapping between the input variables and the
    corresponding input streams should be specified using ``model_inputs_to_streams``.
    The size of the training set can be controlled either during creation of the training minibatch 
    source or using ``max_training_samples`` parameter. 
    Checkpointing, cross validation and progress printing can be configured by calling corresponding
    Set functions.

    Args:
        trainer (:class:`~cntk.trainer.Trainer`): trainer
        training_minibatch_source (:class:`~cntk.io.MinibatchSource`): minibatch source used for training
        mb_size_schedule (:class:`~cntk.cntk_py.minibatch_size_schedule`): minibatch schedule for training
        model_inputs_to_mb_source_mapping (dict): mapping between input variables and input streams
        max_training_samples (int): maximum number of samples used for training
    '''
    def __init__(self, trainer, training_minibatch_source,
                 mb_size_schedule, model_inputs_to_streams,
                 max_training_samples):

        self.trainer = trainer
        self.progress_printer = None
        self.cv_callback = None

        if max_training_samples is None:
            max_training_samples = sys.maxsize

        super(TrainingSession, self).__init__(
            trainer,
            training_minibatch_source,
            mb_size_schedule,
            model_inputs_to_streams,
            max_training_samples)

    @typemap
    def with_checkpointing(self, filename, frequency=None,
                          restore=True, preserve_all=False):
        '''Configuration of checkpointing behavior.

        Args:
            filename (str): checkpoint file name.
            frequency (int): checkpoint frequency in samples. If 0, no checkpointing takes place. 
              If ``sys.maxsize``, a single checkpoint is taken at the end of the training.
            preserve_all (bool): saves all checkpoints, using ``filename`` as prefix and checkpoint index as a suffix.
            restore (bool): flag, indicating whether to restore from available checkpoint before the start of the training
  
        Returns:
            Reconfigured self.
        '''
        if filename is None:
            if frequency is not None and frequency != 0:
                raise ValueError(
                    "Checkpoint frequency cannot be specified without checkpoint_filename")
            frequency = 0
            filename = ""

        if frequency is None:
            frequency = sys.maxsize

        super(TrainingSession, self).with_checkpointing(filename, frequency,
            restore, preserve_all)
        return self

    @typemap
    def with_cross_validation(self, source=None, schedule=None, frequency=None, callback=None):
        '''Configuration of cross validation.

        Args:
            source (:class:`~cntk.io.MinibatchSource`): minibatch source used for cross validation
            frequency (int): frequency in samples for cross validation
              If ``sys.maxsize``, a single cross validation is performed at the end of training.
            schedule (:class:`~cntk.cntk_py.minibatch_size_schedule`): minibatch schedule for cross validation
            callback (func (index, avarage_error, cv_num_samples, cv_num_minibatches)): Callback that will 
              be called with frequency which can implement custom cross validation logic,
              returns False if training should be stopped.

        Returns:
            Reconfigured self.
        '''
        self.cv_callback = callback

        if source is None and callback is None:
            raise ValueError("Either source of callback should be specified.")

        if frequency is None:
            frequency = sys.maxsize

        if schedule is None:
            schedule = minibatch_size_schedule(1)

        if not isinstance(schedule, cntk_py.minibatch_size_schedule):
            raise ValueError('schedule type (%s) not supported. '
                             'it must be an output of minibatch_size_schedule() function'
                             % type(schedule))
        super(TrainingSession, self).with_cross_validation(source, schedule, frequency)
        return self

    @typemap
    def with_progress_printing(self, printer, frequency=None):
        '''Configuration of progress printing.

        Args:
            printer (:class:`~cntk.utils.progress_print.ProgressPrinter`): progress printer
            frequency (int): frequency in samples for aggregated progress printing
        '''
        self.progress_printer = printer

        if frequency is None:
            frequency = sys.maxsize

        super(TrainingSession, self).with_progress_printing(frequency)
        return self

    @typemap
    def train(self, device=None):
        '''
        Perform training on a specified device.

        Args:
            device (:class:~cntk.device.DeviceDescriptor): the device descriptor containing
               the type and id of the device where training takes place.
        '''

        if not device:
            device = use_default_device()

        super(TrainingSession, self).train(device)

    def on_minibatch_end(self):
        '''
        Callback that gets executed at the end of each minibatch.
        '''
        if self.progress_printer and self.trainer.total_number_of_samples_seen != 0:
            self.progress_printer.update_with_trainer(
                self.trainer, with_metric=True)

    def on_progress(self, index):
        '''
        Callback that gets executed with the ``progress_frequency`` frequency in samples.

        Args:
            index (int): index of the current callback.
        '''
        if self.progress_printer:
            self.progress_printer.epoch_summary(with_metric=True)

    def on_cross_validation_end(self, index, average_error, num_samples, num_minibatches):
        '''
        Callback that gets executed at the end of cross validation.

        Args:
            index (int): index of the current callback.
            average_error (float): average error for the cross validation
            num_samples (int): number of samples in cross validation
            num_minibatches (int): number of minibatch in cross validation

        Returns:
            True if training should continue, False otherwise.
        '''
        if self.cv_callback is not None:
            return self.cv_callback(index, average_error, num_samples, num_minibatches)
        elif self.progress_printer:
            msg = "Cross Validation [{}]: Minibatch[1-{}]: errs = {:0.2f}% * {}".format(
                index + 1, num_minibatches, average_error * 100, num_samples)
            self.progress_printer.log(msg)
            return True


@typemap
def minibatch_size_schedule(schedule, epoch_size=1):
    '''
    Create a minibatch size schedule

    Examples:
        >>> # Use a fixed value 32 for all minibatches
        >>> s = minibatch_size_schedule(32)
        >>> s[0], s[1]
        (32, 32)

        >>> # Use minibatches of size 32 for the first 1000 samples, then 64 for the remaining ones
        >>> s = minibatch_size_schedule([32, 64], 1000)
        >>> s[0], s[1], s[1000], s[1001]
        (32, 32, 64, 64)

        >>> # Use 32 for the first 12 epochs, then 64 for the next 15,
        >>> # followed by 128 for the remaining ones, with a 100 samples in an epoch
        >>> s = minibatch_size_schedule([(12, 32), (15, 64), (1, 128)], 100)
        >>> s[0], s[1199], s[1200], s[2699], s[2700], s[5000]
        (32, 32, 64, 64, 128, 128)

    Args:
        schedule (integer or list): if integer, it this minibatch size will be used for the whole training.
         In case of list of integers, the elements are used as the values for ``epoch_size`` samples. 
         If list contains pair, the second element is used as a value for (``epoch_size`` x first element) samples
        epoch_size (int): number of samples as a scheduling unit.

    Returns:
        training parameter schedule
    '''
    if isinstance(schedule, int):
        if epoch_size != 1:
            raise ValueError('when providing the schedule as a number,'
                             ' epoch_size is ignored')
        return cntk_py.minibatch_size_schedule(schedule)

    if isinstance(schedule, list):
        return cntk_py.minibatch_size_schedule(schedule, epoch_size)

    raise ValueError(
        'schedule must be either a float or a list, not %s' % type(schedule))


@typemap
def training_session(training_minibatch_source,
                     trainer, mb_size_schedule,
                     progress_printer=None,
                     model_inputs_to_mb_source_mapping={},
                     checkpoint_filename=None,
                     checkpoint_frequency=None,
                     save_all_checkpoints=False,
                     restore=True,
                     progress_frequency=None,
                     cv_source=None,
                     cv_mb_size_schedule=None,
                     cv_frequency=None,
                     max_training_samples=None):
    '''
    A factory function to create a training session object.

    Args: 
        training_minibatch_source (:class:`~cntk.io.MinibatchSource`): minibatch source used for training
        trainer (:class:`~cntk.trainer.Trainer`): trainer
        mb_size_schedule (:class:`~cntk.cntk_py.minibatch_size_schedule`): minibatch schedule for training
        progress_printer (:class:`~cntk.utils.progress_print.ProgressPrinter`): !DEPRECATED! progress printer
        model_inputs_to_mb_source_mapping (dict): mapping between input variables and input streams
        checkpoint_filename (str): !DEPRECATED! checkpoint file name.
        checkpoint_frequency (int): !DEPRECATED! checkpoint frequency in samples. If 0, no checkpointing takes place. 
          If ``sys.maxsize``, a single checkpoint is taken at the end of the training.
        save_all_checkpoints (bool): !DEPRECATED! saves all checkpoints, using ``checkpoint_filename`` as prefix and checkpoint index as a suffix.
        restore (bool): flag, indicating whether to restore from available checkpoint before the start of the training
        progress_frequency (int): !DEPRECATED! frequency in samples for aggregated progress printing
        cv_source (:class:`~cntk.io.MinibatchSource`): minibatch source used for cross validation
        cv_frequency (int): !DEPRECATED! frequency in samples for cross validation
        cv_mb_size_schedule (:class:`~cntk.cntk_py.minibatch_size_schedule`): minibatch schedule for cross validation
          If ``sys.maxsize``, a single cross validation is performed at the end of training.
        max_training_samples (int): maximum number of samples used for training

    Returns:
        Instance of :class:`~TrainingSession`
    '''
    if checkpoint_filename is not None or   \
       checkpoint_frequency is not None or  \
       save_all_checkpoints != False or     \
       restore != True or                   \
       progress_frequency is not None or    \
       cv_source is not None or             \
       cv_mb_size_schedule is not None or   \
       cv_frequency is not None:
       import warnings
       warnings.warn('The provided parameters will be removed'
           ' in the next beta. Please use only trainer,'
           ' training_minibatch_source, mb_size_schedule and '
           'model_inputs_to_mb_source_mapping. The rest can be '
           'configured using TrainingSession Set... methods.')    

    session = TrainingSession(trainer, training_minibatch_source,
                              mb_size_schedule, model_inputs_to_mb_source_mapping,
                              max_training_samples=max_training_samples)

    if checkpoint_filename is not None:
        session.with_checkpointing(checkpoint_filename, checkpoint_frequency,
            restore, save_all_checkpoints)

    if cv_source is not None:
        session.with_cross_validation(cv_source, cv_mb_size_schedule, cv_frequency)

    if progress_printer is not None:
        session.with_progress_printing(progress_printer, progress_frequency)

    return session
