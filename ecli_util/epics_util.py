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


# TODO i modified this a long time ago -- is it necessary any longer?
def caget(pvname, verbose=True, connection_timeout=0.1, **kwargs):
    if pvname not in _pv_cache:
        _pv_cache[pvname] = epics.PV(pvname,
                                     connection_timeout=connection_timeout)

    pv = _pv_cache[pvname]
    if pv.wait_for_connection(timeout=connection_timeout):
        try:
            return pv.get(**kwargs)
        except Exception as ex:
            if verbose:
                print('caget.get failed for %s: (%s) %s' %
                      (pvname, ex.__class__.__name__, ex))
            return None
        # finally:
        #    pv.disconnect()
    else:
        if verbose:
            print('%s: caget.wait_for_connection failed' % pvname)
        return None

epics.caget = caget


def get_record_type(pv):
    """
    Get the record type
    """
    global _type_cache

    if not pv:
        return ''

    if pv in _type_cache:
        return _type_cache[pv]

    if '.' in pv:
        pv = pv.rsplit('.', 1)[0]

    _type_cache[pv] = caget(RECORD_TYPE_PV % pv,
                            connection_timeout=get_core_plugin().type_timeout)
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
