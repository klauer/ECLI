# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.errors` -- ECLI errors and exceptions
=====================================================

.. module:: ecli_util.errors
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
class ECLIError(Exception): pass
class ExtensionNotLoadedError(ECLIError): pass
class TimeoutError(ECLIError): pass

class AlarmError(ECLIError): pass
class MinorAlarmError(ECLIError): pass
class MajorAlarmError(ECLIError): pass

# Alarm severities
SEV_MINOR = 1
SEV_MAJOR = 2

severity_error_class = {
    SEV_MINOR: MinorAlarmError,
    SEV_MAJOR: MajorAlarmError,
}
