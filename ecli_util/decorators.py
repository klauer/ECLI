# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.decorators` -- ECLI function decorators
==========================================================

.. module:: ecli_util.decorators
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import re
import logging
import shlex
import time
import sys

import functools
from functools import wraps

from . import (get_core_plugin, expand_alias)

# Decorators


def expand_aliases(fcn=None, no_expansion=[]):
    """
    (decorator)
    Expand aliases in a command

    :param fcn: The function to decorate
    :param no_expansion: A list of argument indices to not expand
    """
    if fcn is None:
        # arguments passed to decorator -> no_expansion set
        no_expansion = set(no_expansion)

        def outer_wrap(fcn):
            @wraps(fcn)
            def wrap(self, *args, **kwargs):
                params = [arg if i in no_expansion else expand_alias(arg)
                          for i, arg in enumerate(args)]
                return fcn(self, *args, **kwargs)

            return wrap

        return outer_wrap

    else:
        # no arguments passed to decorator -> expand all arguments
        @wraps(fcn)
        def wrap(self, *args, **kwargs):
            args = [expand_alias(arg) for arg in args]
            return fcn(self, *args, **kwargs)

        return wrap


def evaluate_arguments(fcn):
    """
    (decorator)
    Use the user namespace in IPython to evaluate each argument

    :param fcn: The function to decorate
    """
    # no arguments passed to decorator -> expand all arguments
    @wraps(fcn)
    def wrap(self, *args, **kwargs):
        shell = get_core_plugin().shell
        new_args = []
        for i, param in enumerate(args):
            try:
                new_args.append(shell.ev(param))
            except Exception as ex:
                logging.debug('Unable to evaluate argument %d (%s): (%s) %s' %
                             (i, param, ex.__class__.__name__, ex))
                new_args.append(param)

        return fcn(self, *new_args, **kwargs)

    return wrap


def wrap_command(fcn):
    """
    (decorator)
    Allows exported functions to be called in a simple fashion:

    For example,
        monitor pv
    instead of
        monitor('pv')

    :param fcn: The function to decorate
    """
    @wraps(fcn)  # functools.wraps keeps the introspection info
    def wrap(self, params, **kwargs):
        if isinstance(params, unicode):
            params = params.encode('utf-8')

        # Check if arguments are wrapped in parentheses
        m = re.match('\s*\((.*)\)\s*', params)
        if m:
            params = m.groups()[0]

            params = shlex.split(params)
            # Also remove trailing commas, if they exist
            func_args = [param[:-1] if param.endswith(',') else param
                         for param in params]
        else:
            func_args = shlex.split(params)

        try:
            return fcn(self, *func_args, **kwargs)
        except KeyboardInterrupt:
            print("Cancelling...")

    return wrap


class ShowElapsed(object):
    """
    Decorator for (optionally) showing elapsed times of commands.
    """

    def __init__(self, display_toggle=None, format_='\n  Elapsed: %.3g',
                 file_=sys.stdout):
        """
        :param display_toggle: (optional) callable that determines whether
            or not the elapsed time should be displayed
        :param format_: Format to print the elapsed time
        :param file_: Destination to print to
        """

        self.format_ = format_
        self.display_toggle = display_toggle
        self.file_ = file_
        if self.display_toggle is not None:
            assert(hasattr(self.display_toggle, '__call__'))

    def wrapper(self, fcn):
        @wraps(fcn)
        def wrap(*args, **kwargs):
            t0 = time.time()
            try:
                return fcn(*args, **kwargs)
            finally:
                elapsed = time.time() - t0

                display = True
                if self.display_toggle is not None:
                    if not self.display_toggle():
                        display = False

                if display:
                    print(self.format_ % elapsed, file=self.file_)

        return wrap


class ECLIExported(object):
    """ECLI exported function"""
    pass


#class ECLIExport(object):
#    """ECLI exported function"""
#    # Simple decorator to indicate the function should be exported to the user
#    # namespace
#    def __init__(self, fcn):
#        self.fcn = fcn
#        functools.update_wrapper(self, fcn)
#        self.decorators = [self]
#
#    def __call__(self, *args, **kwargs):
#        return self.fcn(*args, **kwargs)

def ECLIExport(fcn):
    """
    Simple decorator to indicate the function should be exported to the user
    namespace
    """
    @wraps(fcn)
    def wrapped(*args, **kwargs):
        return fcn(*args, **kwargs)

    wrapped.decorators = [ECLIExported()]
    return wrapped
