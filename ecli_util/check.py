# -*- coding: utf-8 -*-
# vi:sw=4 ts=4

"""
:mod:`ecli_util.check` -- Simple string conversion checks
=========================================================

.. module:: ecli_util.check
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from IPython.core.error import UsageError

TRUE_VALUES = ('on', 'yes', '1', 'true')
FALSE_VALUES = ('off', 'no', '0', 'false')


def check_bool(value):
    """Ensures a proper boolean value (even from a string). Raises UsageError on failure"""
    try:
        v = str(value).lower()
        if v not in TRUE_VALUES and v not in FALSE_VALUES:
            raise

        return (v in TRUE_VALUES)
    except:
        raise UsageError('Invalid boolean value: "%s"' % value)


def check_int(value):
    """Ensures a proper integer value (from a string). Raises UsageError if not"""
    try:
        return int(value)
    except:
        raise UsageError('Invalid integer value: "%s"' % value)


def check_float(value):
    """Ensures a proper floating-point value. Raises UsageError if not"""
    try:
        return float(value)
    except:
        raise UsageError('Invalid float value: "%s"' % value)
