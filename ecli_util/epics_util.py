# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.epics_util` -- ECLI epics utilities
===================================================

.. module:: ecli_util.epics_util
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import re
import epics

from . import get_core_plugin
import errors

RE_FIELD = re.compile('^([^.a-z]{0,5})$')
MOTOR_RBV_PV = "%s.RBV"
RECORD_TYPE_PV = "%s.RTYP"


def split_record_field(pv):
    if '.' in pv:
        record, field = pv.rsplit('.', 1)
    else:
        record, field = pv, ''

    return record, field


def is_valid_field_name(field):
    m = RE_FIELD.match(field)
    return m.groups() is not None

_type_cache = {}
_pv_cache = {}


def caget(pvname, connection_timeout=5.0, verbose=True, **kwargs):
    # For future pyepics reference:
    # * The reason behind wrapping epics.caget is that there's no nice way to
    #   differentiate between connection_timeout and caget timeout with epics.caget.
    # * The default of 5 seconds in epics.__create_pv can be excruciatingly slow.
    # * A verbosity setting
    if pvname not in _pv_cache:
        _pv_cache[pvname] = epics.PV(pvname,
                                     connection_timeout=connection_timeout)

    pv = _pv_cache[pvname]
    if pv.wait_for_connection(timeout=connection_timeout):
        if kwargs.get('as_string', False):
            pv.get_ctrlvars()

        epics.poll()
        try:
            value = pv.get(**kwargs)
            return value
        except Exception as ex:
            if verbose:
                print('caget.get failed for %s: (%s) %s' %
                      (pvname, ex.__class__.__name__, ex))
            return None
    else:
        if verbose:
            print('%s: failed to connect to PV' % pvname)
        return None


if not hasattr(epics, '__caget__'):
    epics.__caget__ = epics.caget
    epics.caget = caget


def get_record_type(pv):
    """
    Get the record type
    """
    global _type_cache

    pv = strip_field(pv)

    rtyp_pv = RECORD_TYPE_PV % pv

    if not pv:
        return ''
    elif pv in _type_cache:
        return _type_cache[pv]

    _type = caget(rtyp_pv,
                  connection_timeout=get_core_plugin().type_timeout)

    if _type is None:
        return ''
    else:
        _type_cache[pv] = _type
        return _type_cache[pv]


def strip_field(pv):
    if '.' in pv:
        pv = pv.rsplit('.', 1)[0]
    return pv


def is_motor_record(rec):
    """
    Is rec an actual motor record?
    """
    return (get_record_type(rec) == 'motor')


def is_scan_record(rec):
    """
    Is rec an actual sscan record?
    """
    # TODO: unused
    return (get_record_type(rec) == 'sscan')


def pv_field(pv_or_record, field):
    record, field = split_record_field(pv_or_record)
    return '%s.%s' % (record, field)


def get_motor_rbv_pv(motor):
    """
    Get the associated (user) readback-value PV from a given motor record.
    """
    record, field = split_record_field(motor)
    # Strip off the .VAL field if necessary
    if field == '.VAL':
        motor = record

    if not is_motor_record(motor):
        raise ValueError('not a motor record')

    return MOTOR_RBV_PV % motor


def get_motor_limits(motor_rec):
    """
    Get the user limits, given a motor record
    """
    try:
        motor = epics.Motor(motor_rec)
    except epics.motor.MotorException:  # Not a motor record
        return None, None
    else:
        return motor.low_limit, motor.high_limit


def check_alarm(base_pv, stat_field='STAT', severity_field='SEVR',
                reason_field=None, reason_pv=None,
                min_severity=errors.SEV_MINOR):
    """
    Raise an exception if an alarm is set
    """
    stat_pv = '%s.%s' % (base_pv, stat_field)
    severity_pv = '%s.%s' % (base_pv, severity_field)
    if reason_field is not None:
        reason_pv = '%s.%s' % (base_pv, reason_field)
    reason = None

    severity = epics.caget(severity_pv)

    if severity >= min_severity:
        try:
            error_class = errors.severity_error_class[severity]
        except KeyError:
            pass
        else:
            severity = epics.caget(severity_pv, as_string=True)
            alarm = epics.caget(stat_pv, as_string=True)
            if reason_pv is not None:
                reason = epics.caget(reason_pv, as_string=True)

            message = 'Alarm status %s [severity %s]' % (alarm, severity)
            if reason is not None:
                message = '%s: %s' % (message, reason)

            raise error_class(message)

    return True
