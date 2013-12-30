# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.epics_device` -- ECLI pyEpics device utilities
==============================================================

.. module:: ecli_util.epics_device
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
import epics
from . import expand_alias


def get_record_from_device(s):
    """
    If the device is an epics.Device instance, return
    just the expanded PV.

    :return: a PV, or raises UsageError if invalid
    """
    if isinstance(s, epics.Device):
        # remove the '.' from the prefix to get the record name
        return s._prefix.rstrip('.')
    elif isinstance(s, (str, unicode)):
        return expand_alias(s)
    else:
        # TODO: what should we do here?
        raise TypeError('Unknown type')


def get_records_from_devices(device_list):
    """
    Like `get_record_from_device` but accepts a list of devices/records.
    """
    return [get_record_from_device(s) for s in device_list]
