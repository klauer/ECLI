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

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util.epics_device import (get_record_from_device,
                                    get_records_from_devices, )
from ecli_util.decorators import ECLIExport
from ecli_util.magic_args import (ecli_magic_args, argument)

import epics

logger = logging.getLogger('ECLI.Motor')
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
        self.motors = {}

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
            try:
                expanded = util.expand_alias(motor)
                motor_inst = epics.Motor(expanded)
            except Exception as ex:
                logger.error('Bad motor: %s (%s) %s'
                             % (motor, ex.__class__.__name__, ex))
            except KeyboardInterrupt:
                logger.warning('Skipping motor list entry: %s' % motor)
            else:
                self.motors[motor] = motor_inst

                if util.is_valid_python_identifier(motor):
                    shell.user_ns[motor] = motor_inst

    def get_motor(self, motor):
        try:
            return self.motors[motor]
        except:
            self.motors[motor] = epics.Motor(motor)
            return self.motors[motor]

    def __iter__(self):
        for name, motor in self.motors.items():
            yield name, motor

    def __getitem__(self, name):
        return self.motors[name]

    @ECLIExport
    def wa(self):
        """
        Show status of all motors in ECLIMotor.motor_list
        """
        motors = self.motor_list
        if motors:
            self.print_motor_info(motors)
        else:
            logger.error('ECLIMotor.motor_list unset')

    @ECLIExport
    def move_motor(self, motor_rec, offset_or_position, relative=True, wait=True,
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
    def user_move_motor(self, motor, offset_or_position, verbose=True, **kwargs):
        '''
        For moving motors from the command line -- catch exceptions so as to not
        flood the command line when hitting limits, for example

        Accepts either motor instances or (optionally aliased) record names
        '''
        try:
            motor = get_record_from_device(motor)
            self.move_motor(motor, offset_or_position, verbose=verbose, **kwargs)
        except epics.motor.MotorLimitException as ex:
            print('%s' % ex)
        except Exception as ex:
            print('Failed: (%s) %s' % (ex.__class__.__name__, ex))

    @ECLIExport
    def umvr(self, motor, offset, verbose=True, **kwargs):
        """
        Verbosely move motor by offset, in user coordinates
        """
        return self.user_move_motor(motor, offset,
                                    relative=True, verbose=verbose,
                                    **kwargs)

    @ECLIExport
    def mvr(self, motor, offset, verbose=False, **kwargs):
        """
        Move motor by offset, in user coordinates
        """
        return self.user_move_motor(motor, offset,
                                    relative=True, verbose=verbose,
                                    **kwargs)

    @ECLIExport
    def umv(self, motor, pos, verbose=True, **kwargs):
        """
        Verbosely move motor to absolute position, in user coordinates
        """
        return self.user_move_motor(motor, pos,
                                    relative=False, verbose=verbose,
                                    **kwargs)

    @ECLIExport
    def mv(self, motor, pos, verbose=False, **kwargs):
        """
        Move motor to absolute position, in user coordinates
        """
        return self.user_move_motor(motor, pos,
                                    relative=False, verbose=verbose,
                                    **kwargs)

    def print_motor_info(self, motors):
        '''
        motors:
        '''
        if not motors:
            return

        motors = get_records_from_devices(motors)

        info_dict = self._info_dict

        # TODO convert this to the SimpleTable thing eventually
        motor_info = util.get_structured_pv_info(info_dict, prefix=motors)

        format_ = u'%%.%df' % self.precision
        rows = list(util.format_structured_pv_info(
            motor_info, column_headers=[''] + list(motors), format_=format_))

        util.print_table(rows, first_column_format=u'{:<%d}')


@ecli_magic_args(ECLIMotor)
@argument('motors', type=AliasedPV, nargs='+',
          help='Motor(s) to query')
def wm(mself, self, args):
    """
    Show motor status
    """
    self.print_motor_info(args.motors)


@ecli_magic_args(ECLIMotor)
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('offset', type=float,
          help='Position offset to move')
@argument('-v', '--verbose', action='store_const', const=True,
          help='Move verbosely')
def mvr(mself, self, args):
    """
    Move motor by offset, in user coordinates
    """
    self.user_move_motor(args.motor, args.offset, relative=True,
                         verbose=args.verbose)


@ecli_magic_args(ECLIMotor)
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('offset', type=float,
          help='Position offset to move')
def umvr(mself, self, args):
    """
    Verbosely move motor by offset, in user coordinates
    """
    self.user_move_motor(args.motor, args.offset, relative=True, verbose=True)


@ecli_magic_args(ECLIMotor)
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('position', type=float)
@argument('-v', '--verbose', action='store_const', const=True,
          help='Move verbosely')
def mv(mself, self, args):
    """
    Move motor to absolute position, in user coordinates
    """
    self.user_move_motor(args.motor, args.position, relative=False,
                         verbose=args.verbose)


@ecli_magic_args(ECLIMotor)
@argument('motor', type=AliasedPV,
          help='Motor to move')
@argument('position', type=float)
def umv(mself, self, args):
    """
    Verbosely move motor to absolute position, in user coordinates
    """
    self.user_move_motor(args.motor, args.position, relative=False, verbose=True)


@ecli_magic_args(ECLIMotor)
@argument('motor', type=AliasedPV,
          help='Motor to stop')
def mstop(mself, self, args):
    """
    Stop motor
    """
    device = epics.motor.Motor(args.motor)
    device.stop()
