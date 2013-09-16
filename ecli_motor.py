# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_motor` -- ECLI motor record support
==============================================

.. module:: ecli_motor
   :synopsis: PyEpics motor record plugin for ECLI
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import logging

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (argument, magic_arguments,
                                          parse_argstring)

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import get_plugin
from ecli_util.epics_device import (get_records_from_devices, )
from ecli_util.decorators import ECLIExport

import epics

logger = logging.getLogger('ECLIMotor')
motor_field_info = util.get_record_fields('motor')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIMotor, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIMotor)


DEFAULT_MOTOR_INFO = {
    'User': {
        'High': '.HLM',
        'Current': '.RBV',
        'Low': '.LLM',
    },

    'Dial': {
        'High': '.DHLM',
        'Current': '.DRBV',
        'Low': '.DLLM',
    },

}

MOTOR_MOVING_PV = "%s.MOVN"


class ECLIMotor(ECLIPlugin):

    """
    Motor record interface plugin for ECLI
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    _callbacks = []
    motor_list = traitlets.List(traitlets.Unicode,
                                default_value=(),
                                config=True)
    additional_fields = traitlets.List(traitlets.Unicode,
                                       default_value=(),
                                       config=True)

    precision = traitlets.Int(8, config=True)

    def __init__(self, shell, config):
        self._info_dict = DEFAULT_MOTOR_INFO
        super(ECLIMotor, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI motor plugin')

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIMotor')

    @property
    def logger(self):
        return logger

    def _additional_fields_changed(self, *args):
        if self.additional_fields:
            self._info_dict['(Other)'] = d = {}
            for field in self.additional_fields:
                try:
                    desc = motor_field_info.descriptions[field]
                    print('Motor field %s (%s)' % (field, desc))
                    d[desc] = '.%s' % field
                except KeyError:
                    print('Ignoring unknown motor field %s' % field)
        else:
            try:
                del self._info_dict['(Other)']
            except KeyError:
                pass

    def _motor_list_changed(self, *args):
        shell = self.shell
        new_motors = [motor for motor in self.motor_list
                      if motor not in shell.user_ns]

        for motor in new_motors:
            if util.is_valid_python_identifier(motor):
                expanded = util.expand_alias(motor)
                try:
                    shell.user_ns[motor] = epics.Motor(expanded)
                except Exception as ex:
                    logger.error('Bad motor "%s" (%s) %s'
                                 % (motor, ex.__class__.__name__, ex))
                except KeyboardInterrupt:
                    logger.warning('Skipping motor list entry "%s"' % motor)

        # TODO remove old motors or just leave them in the user namespace?


def print_motor_info(motors):
    '''
    motors:
    '''
    if not motors:
        return

    motors = get_records_from_devices(motors)

    plugin = get_plugin('ECLIMotor')
    info_dict = plugin._info_dict

    # TODO convert this to the SimpleTable thing eventually
    motor_info = util.get_structured_pv_info(info_dict, prefix=motors)

    format_ = u'%%.%df' % plugin.precision
    rows = list(util.format_structured_pv_info(
        motor_info, column_headers=[''] + list(motors), format_=format_))

    util.print_table(rows, first_column_format=u'{:<%d}')


@magic_arguments()
@argument('motors', type=AliasedPV, nargs='+',
          help='Motor(s) to query')
def wm(self, arg):
    """
    Show motor status
    """
    args = parse_argstring(wm, arg)
    if args:
        print_motor_info(args.motors)


@ECLIExport
def wa():
    """
    Show status of all motors in ECLIMotor.motor_list
    """
    plugin = get_plugin('ECLIMotor')
    motors = plugin.motor_list
    if motors:
        print_motor_info(motors)
    else:
        logger.error('ECLIMotor.motor_list unset')


@ECLIExport
def move_motor(motor_rec, offset_or_position, relative=True, wait=True,
               update_cb=None, verbose=True, stop_on_ctrlc=True):
    """
    Move a motor record to a specific position, either using relative or absolute
    positioning.

    verbose mode shows the motion of the motor until it stops.
    """
    motor_rec = util.get_record_from_device(motor_rec)

    rbv_pv = util.get_motor_rbv_pv(motor_rec)
    if relative:
        offset = offset_or_position
        current_position = epics.caget(rbv_pv)
        if current_position is None:
            return

        new_position = float(current_position) + offset
    else:
        new_position = offset_or_position

    low_limit, high_limit = util.get_motor_limits(motor_rec)

    device = epics.motor.Motor(motor_rec)
    units = device.units

    if low_limit is not None and high_limit is not None:
        if not (low_limit < new_position < high_limit):
            if new_position < low_limit:
                s_err = 'Position < low limit %g %s' % (low_limit, units)
                raise epics.motor.MotorLimitException(s_err)
            elif new_position > high_limit:
                s_err = 'Position > high limit %g %s' % (high_limit, units)
                raise epics.motor.MotorLimitException(s_err)

    print('Moving %s to %g' % (motor_rec, new_position))

    if wait:
        def updated(pvname='', value='', **kwargs):
            util.print_sameline('\t%s %s' % (value, units))

        if update_cb is None and verbose:
            update_cb = updated

        monitor = util.ConditionalMonitor(rbv_pv,
                                          desired_value=new_position,
                                          stop_condition_pv=MOTOR_MOVING_PV % motor_rec,
                                          stop_pv_value=(0, 1, 0),
                                          update_cb=update_cb)

        epics.caput(motor_rec, new_position)
        monitor.wait()
        if stop_on_ctrlc and monitor.aborted:
            if verbose:
                print()
                print('Stopping motor at %g %s' % (epics.caget(rbv_pv), units))

            device.stop()

        if verbose:
            print()

    else:
        epics.caput(motor_rec, new_position)

    device.check_limits()


@ECLIExport
def user_move_motor(motor, offset_or_position, verbose=True, **kwargs):
    '''
    For moving motors from the command line -- catch exceptions so as to not
    flood the command line when hitting limits, for example
    '''
    try:
        move_motor(motor, offset_or_position, verbose=verbose, **kwargs)
    except epics.motor.MotorLimitException as ex:
        print('%s' % ex)
    except Exception as ex:
        print('Failed: (%s) %s' % (ex.__class__.__name__, ex))


@magic_arguments()
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('offset', type=float,
          help='Position offset to move')
@argument('-v', '--verbose', action='store_const', const=True,
          help='Move verbosely')
def mvr(self, arg):
    """
    Move motor by offset, in user coordinates
    """
    args = parse_argstring(mvr, arg)
    if args:
        user_move_motor(args.motor, args.offset, relative=True,
                        verbose=args.verbose)


@magic_arguments()
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('offset', type=float,
          help='Position offset to move')
def umvr(self, arg):
    """
    Verbosely move motor by offset, in user coordinates
    """
    args = parse_argstring(mvr, arg)
    if args:
        user_move_motor(args.motor, args.offset, relative=True, verbose=True)


@magic_arguments()
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('position', type=float)
@argument('-v', '--verbose', action='store_const', const=True,
          help='Move verbosely')
def mv(self, arg):
    """
    Move motor to absolute position, in user coordinates
    """
    args = parse_argstring(mv, arg)
    if args:
        user_move_motor(args.motor, args.position, relative=False,
                        verbose=args.verbose)


@magic_arguments()
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('position', type=float)
def umv(self, arg):
    """
    Verbosely move motor to absolute position, in user coordinates
    """
    args = parse_argstring(umv, arg)
    if args:
        user_move_motor(args.motor, args.position, relative=False, verbose=True)


@magic_arguments()
@argument('motor', type=AliasedPV,
          help='Motor to stop')
def mstop(self, arg):
    """
    Stop motor
    """
    args = parse_argstring(mstop, arg)
    if args:
        device = epics.motor.Motor(args.motor)
        device.stop()
