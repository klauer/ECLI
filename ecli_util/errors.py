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
