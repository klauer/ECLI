# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_cas.soft_motor` -- ECLI Soft Motor
=============================================

.. module:: ecli_cas.soft_motor
   :synopsis: ECLI soft motor
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function

import logging

from .record import CASRecord
from . import motor_info as mi
from . import record

from . import CAPVBadValue

logger = logging.getLogger('ECLI.soft_motor')


class SoftMotorError(Exception): pass
class SoftMotorLimitError(CAPVBadValue): pass


STATUS_BITS = {'direction': 0,         # last raw direction; (0:Negative, 1:Positive)
               'done': 1,              # motion is complete.
               'plus_ls': 2,           # plus limit switch has been hit.
               'homels': 3,            # state of the home limit switch.

               'position': 5,          # closed-loop position control is enabled.
               'slip_stall': 6,        # Slip/Stall detected (eg. fatal following error)
               'home': 7,              # if at home position.
               'enc_present': 8,       # encoder is present.
               'problem': 9,           # driver stopped polling, or hardware problem
               'moving': 10,           # non-zero velocity present.
               'gain_support': 11,     # motor supports closed-loop position control.
               'comm_err': 12,         # Controller communication error.
               'minus_ls': 13,         # minus limit switch has been hit.
               'homed': 14,            # the motor has been homed.
               }


class SoftMotor(CASRecord):
    def __init__(self, manager, name):
        CASRecord.__init__(self, manager, name,
                           rtype='motor', dtype='Soft Motor')

        for field, (alias, type_, defaults) in mi.MOTOR_FIELDS.items():
            info = record.create_field_info(type_, defaults)
            if field.endswith('VAL'):
                info['asyn'] = True

            self.add_field(field, info, alias=alias)

        self._offset = 0.0
        self._go = mi.MOTOR_GO_DEFAULT
        self._direction = 0

        self._motor_res = mi.MOTOR_RES_DEFAULT
        self._encoder_res = mi.MOTOR_RES_DEFAULT

        # internally, store only dial coordinates
        self._high_limit = self.get_field_default(mi.MOTOR_DIAL_HIGH_LIMIT)
        self._low_limit = self.get_field_default(mi.MOTOR_DIAL_LOW_LIMIT)

        self._moving = False
        self._request_position = None
        self._paused_position = None
        self._readback = 0.0
        self._value = 0.0
        self._move_direction = 0.0
        self._tweak_value = self.get_field_default(mi.MOTOR_TWEAK_VALUE)
        self._status = 0
        self._done_moving = True
        self._updating = False

    def get_field_default(self, field):
        average, min_, max_ = mi.get_field_defaults(field)
        return average

    def __repr__(self):
        return '%s(_record_name=%s)' % (self.__class__.__name__, self.name)

    def go_updated(self, value=None, **kwargs):
        self._go = value
        if value == mi.MOTOR_GO_GO and self._paused_position is not None:
            logger.debug('%s: Paused position: %s' % (self, self._paused_position))
            self.move(self._paused_position, relative=False)
            self._paused_position = None

    def startup(self, driver):
        CASRecord.startup(self, driver)

        self.set_field(mi.MOTOR_DONE_MOVE, self._done_moving)
        self.update_status(enc_present=True)

    def _positions(self, value, type_):
        """for a given position, returns the (user, dial, raw) positions"""
        res = self._motor_res
        if res == 0.0:
            raise ValueError('Resolution unset')

        if type_ == mi.POSITION_RAW:
            dial = res * value
            user = dial + self._offset
            if self._direction == mi.MOTOR_DIRECTION_NEG:
                user *= -1.0
            return user, dial, int(value)

        if type_ == mi.POSITION_DIAL:
            user, dial = value - self._offset, value
            if self._direction == mi.MOTOR_DIRECTION_NEG:
                user *= -1.0
        elif type_ == mi.POSITION_USER:
            user, dial = value, value + self._offset

        return user, dial, int(dial / res)

    def _update_high_limit(self, limit, position_type=mi.POSITION_DIAL):
        user, dial, raw = self._positions(limit, position_type)
        self._high_limit = dial

        with self._no_callbacks():
            if position_type == mi.POSITION_DIAL:
                self.set_field(mi.MOTOR_USER_HIGH_LIMIT, user)
            else:
                self.set_field(mi.MOTOR_DIAL_HIGH_LIMIT, dial)

        for field in ('', 'VAL'):
            self.update_pvinfo(field, 'hilim', user)
        for field in ('DVAL', ):
            self.update_pvinfo(field, 'hilim', dial)
        for field in ('RVAL', ):
            self.update_pvinfo(field, 'hilim', raw)

    def _update_low_limit(self, limit, position_type=mi.POSITION_DIAL):
        user, dial, raw = self._positions(limit, position_type)
        self._low_limit = dial
        with self._no_callbacks():
            if position_type == mi.POSITION_DIAL:
                self.set_field(mi.MOTOR_USER_LOW_LIMIT, user)
            else:
                self.set_field(mi.MOTOR_DIAL_LOW_LIMIT, dial)

        for field in ('', 'VAL'):
            self.update_pvinfo(field, 'lolim', user)
        for field in ('DVAL', ):
            self.update_pvinfo(field, 'lolim', dial)
        for field in ('RVAL', ):
            self.update_pvinfo(field, 'lolim', raw)

    def user_high_limit_updated(self, value=None, **kwargs):
        self._update_high_limit(value, mi.POSITION_USER)

    def user_low_limit_updated(self, value=None, **kwargs):
        self._update_low_limit(value, mi.POSITION_USER)

    def dial_high_limit_updated(self, value=None, **kwargs):
        self._update_high_limit(value)

    def dial_low_limit_updated(self, value=None, **kwargs):
        self._update_low_limit(value)

    def _update_limits(self):
        self.dial_high_limit_updated(value=self._high_limit)
        self.dial_low_limit_updated(value=self._low_limit)

    def motor_res_updated(self, value=None, **kwargs):
        self._motor_res = value

    def encoder_res_updated(self, value=None, **kwargs):
        self._encoder_res = value

    def direction_updated(self, value=None, **kwargs):
        self._direction = value
        self._update_limits()

    def variable_offset_updated(self, value=None, **kwargs):
        self._offset = value
        self._update_limits()
        self._set_readback(self._readback)

    @property
    def request_position(self):
        if self._request_position is None:
            return self._readback
        else:
            return self._request_position

    def tweak_size_updated(self, value=None, **kwargs):
        self._tweak_value = value

    def tweak_reverse_updated(self, value=None, **kwargs):
        if self._direction == mi.MOTOR_DIRECTION_POS:
            pos = self.request_position - self._tweak_value
        else:
            pos = self.request_position + self._tweak_value
        self.move(pos, relative=False)

    def tweak_forward_updated(self, value=None, **kwargs):
        if self._direction == mi.MOTOR_DIRECTION_POS:
            pos = self.request_position + self._tweak_value
        else:
            pos = self.request_position - self._tweak_value

        self.move(pos, relative=False)

    def move(self, amount, relative=False):
        if relative:
            pos = self._readback + amount
            logger.debug('--> Move %s rel: %g pos: %g' % (self, amount, pos))
        else:
            pos = amount
            logger.debug('--> Move %s position: %g' % (self, pos))

        if pos > self._high_limit:
            self.set_field(mi.MOTOR_LIMIT_VIOLATION, 1)
            raise SoftMotorLimitError()
        elif pos < self._low_limit:
            self.set_field(mi.MOTOR_LIMIT_VIOLATION, 1)
            raise SoftMotorLimitError()

        self.set_field(mi.MOTOR_LIMIT_VIOLATION, 0)
        self.set_field(mi.MOTOR_AT_LOW_LIMIT, 0)
        self.set_field(mi.MOTOR_AT_HIGH_LIMIT, 0)

        user, dial, raw = self._positions(pos, mi.POSITION_DIAL)
        with self._no_callbacks():
            self.set_field(mi.MOTOR_DIAL_VALUE, dial)
            self.set_field(mi.MOTOR_USER_VALUE, user)
            self.set_field(mi.MOTOR_RAW_VALUE, raw)

        if self._go != mi.MOTOR_GO_GO:
            logger.debug('Move requested; motor stopped')
            self._paused_position = pos
        else:
            self._request_position = pos

        logger.debug('Move() done')
        self._set_readback(pos)

    def _set_readback(self, dial_position, direction=None):
        logger.debug('%s: Set readback (dial=%s dir=%s)' % (self, dial_position, direction))
        self._readback = dial_position

        user, dial, raw = self._positions(dial_position, mi.POSITION_DIAL)
        if direction is not None:
            self.set_field(mi.MOTOR_MOVE_DIRECTION, direction)

        if self._request_position is None:
            self._request_position = dial
            self.set_field(mi.MOTOR_DIAL_VALUE, dial, update_callback=False)
            self.set_field(mi.MOTOR_USER_VALUE, user, update_callback=False)
            self.set_field(mi.MOTOR_RAW_VALUE, raw, update_callback=False)

        self.set_field(mi.MOTOR_USER_READBACK, user)
        self.set_field(mi.MOTOR_DIAL_READBACK, dial)
        self.set_field(mi.MOTOR_RAW_READBACK, raw)
        #self._update()

        plus_lim = (dial_position >= self._high_limit)
        minus_lim = (dial_position <= self._low_limit)
        self.update_status(plus_ls=plus_lim, minus_ls=minus_lim)

    def dial_value_updated(self, value=None, **kwargs):
        if self._updating:
            return

        return self.move(value, relative=False)

    def raw_value_updated(self, value=None, **kwargs):
        if self._updating:
            return

        user, dial, raw = self._positions(value, mi.POSITION_RAW)
        return self.move(value, relative=False)

    def user_value_updated(self, value=None, **kwargs):
        if self._updating:
            return

        user, dial, raw = self._positions(value, mi.POSITION_USER)
        return self.move(value, relative=False)

    def update_status(self, **kwargs):
        for arg, value in kwargs.iteritems():
            bit = STATUS_BITS[arg]
            if value:
                self._status |= (1 << bit)
            else:
                self._status &= ~(1 << bit)

        self.set_field(mi.MOTOR_STATUS, self._status)

    def _get_done_moving(self):
        return self._done_moving

    def _set_done_moving(self, done_moving):
        if done_moving != self._done_moving:
            self._done_moving = done_moving
            self.update_status(moving=not done_moving, done=done_moving)
            self.set_field(mi.MOTOR_DONE_MOVE, done_moving)

            if done_moving:
                # here's where the response to the putCallback happens
                # that is, the message to the client that the put has complete
                for field in mi.MOTOR_ASYN_FIELDS:
                    self._driver.callbackPV(self._get_full_pv(field))

    done_moving = property(_get_done_moving, _set_done_moving)


def _test():
    from . import PVManager
    import epics

    manager = PVManager('ECLI:')
    manager.run()

    record = SoftMotor(manager, 'test')
    print(epics.caget('ECLI:test.VAL'), record)

    epics.caput('ECLI:test.VAL', 5)
    epics.caput('ECLI:test.TWF', 1)
    epics.caput('ECLI:test.TWR', 1)
