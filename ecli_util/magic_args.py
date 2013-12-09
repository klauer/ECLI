# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.magic_args` -- IPython magic_args helpers
=========================================================

.. module:: ecli_util.magic_args
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
import logging
import argparse
import functools

from IPython.core.error import UsageError
from IPython.core.magic_arguments import argument
from IPython.core.magic_arguments import magic_arguments

from . import expand_alias
from .decorators import ECLIExported
try:
    import epics
except:
    class epics:
        class Device:
            pass


EXPORT_TAG = 'ipy_'
logging.basicConfig()


def argument_count_range(nmin=None, nmax=None):
    """
    For magic arguments, sets a minimum number/maximum number of arguments.
    Partly from http://stackoverflow.com/questions/4194948
    """
    assert(nmin is not None or nmax is not None)

    class RequiredLength(argparse.Action):
        """Sets a minimum number/maximum number of arguments."""

        def __call__(self, parser, args, values, option_string=None):
            if nmin is None:
                if len(values) > nmax:
                    raise UsageError('argument "{f}" requires at most {nmax} arguments'.format(
                                     f=self.dest, nmax=nmax))
            elif nmax is None:
                if len(values) < nmin:
                    raise UsageError('argument "{f}" requires at least {nmin} arguments'.format(
                                     f=self.dest, nmin=nmin))
            elif not nmin <= len(values) <= nmax:
                raise UsageError('argument "{f}" requires between {nmin} and {nmax} arguments'.format(
                    f=self.dest, nmin=nmin, nmax=nmax))

            setattr(args, self.dest, values)

    return RequiredLength

argument_or_flag = argument_count_range(0, 1)


def arg_value_range(min_=None, max_=None, inclusive=True, type_=int):
    def check(value):
        try:
            value = type_(value)
        except:
            raise argparse.ArgumentTypeError(
                "%s is not a valid %s" % (value, type_))

        equals = {True: '=', False: ''}[inclusive]
        if max_ is None:
            if value < min_ or (value == min_ and not inclusive):
                raise argparse.ArgumentTypeError(
                    "%s should be >%s %s" % (value, equals, min_))
        elif min_ is None:
            if value > max_ or (value == max_ and not inclusive):
                raise argparse.ArgumentTypeError(
                    "%s should be <%s %s" % (value, equals, max_))
        else:
            if value > max_ or value < min_ or (not inclusive and (value == max_ or value == min_)):
                raise argparse.ArgumentTypeError("%s should be in the range %s <%s x <%s %s" % (
                    value, min_, equals, equals, max_))
        return value

    return check


class AliasedPV(str):

    """
    Used for magic_arguments (argparse), it allows for automatic
    expansion of PV aliases
    """
    def __new__(self, pv):
        if isinstance(pv, epics.Device):
            return pv._prefix.rstrip('.')

        return str.__new__(self, expand_alias(pv))


def export_magic_by_prefix(ipython, ns, prefix=EXPORT_TAG, strip_prefix=True):
    """
    Functions/classes/etc that start with `prefix` will be exported (i.e., accessible in ipython)
    to the user namespace

    :param ipython: the IPython shell instance
    :param ns: the namespace (e.g., globals()) to check for functions
    :param prefix: the prefix to check for
    :param strip_prefix: strip off the prefix before exporting
    """
    for name, obj in ns.iteritems():
        if name.startswith(prefix):
            if strip_prefix:
                exported_name = name[len(prefix):]

            ipython.define_magic(exported_name, obj)
            logging.debug('Magic defined: %s=%s' % (exported_name, obj))
            if exported_name in ns:
                ipython.user_ns[exported_name] = ns[exported_name]
                logging.debug('Related function imported into user namespace: %s=%s' %
                             (exported_name, ns[exported_name]))


def export_magic_by_decorator(ipython, obj,
                              magic_arguments=True, modify_name=None,
                              strip_underscores=True, wrap_fcn=None):
    """
    Functions that are decorated with specific decorators will be exported
    to the user in IPython.

    :param ipython: the IPython shell instance
    :param obj: the namespace (e.g., globals()) to check for functions,
                or alternatively, an instance of a class
    :param magic_arguments: export functions decorated with magic_arguments
    :type magic_arguments: bool
    :param strip_underscores: remove underscores from beginning of function
                              name.  This is useful if exported func() and
                              magic %func both exist.
    :param modify_name: callback optionally allowing to change the exported
                        name. new_name = modify_name(old_name, obj)
                        strip_underscores is ignored if this is used.
    :param wrap_fcn: optionally wrap the function prior to exporting it
    """
    all_decorators = set([ECLIExported])
    if magic_arguments:
        all_decorators.add(argument)

    is_instance = not isinstance(obj, dict)
    if is_instance:
        class_ = obj.__class__
        ns = class_.__dict__
    else:
        ns = obj

    for name, o in ns.iteritems():
        if not hasattr(o, 'decorators'):
            continue

        try:
            decorators = set([dec.__class__ for dec in o.decorators])
        except:
            continue

        #print(name, decorators)
        matches = decorators.intersection(all_decorators)
        if matches:
            if is_instance:
                fcn = getattr(obj, name)
                #print('-->', fcn)
            else:
                fcn = o

            if wrap_fcn is not None:
                fcn = wrap_fcn(fcn)

            if modify_name is not None:
                name = modify_name(name, fcn)
            elif strip_underscores:
                name = name.lstrip('_')

            if ECLIExported in matches:
                ipython.user_ns[name] = fcn
                logging.debug('Function exported: %s=%s' % (name, fcn))
            else:
                ipython.define_magic(name, fcn)
                logging.debug('Magic defined: %s=%s' % (name, fcn))

def export_class_magic(ipython, instance):
    """
    Functions of a class instance that are decorated with specific
    decorators will be exported to the user in IPython.

    :param ipython: the IPython shell instance
    :param instance: the class instance to look check via introspection
    """
    def wrap(fcn):
        @functools.wraps(fcn)
        def wrapped(*args):
            return fcn(*args)
        return wrapped

    return export_magic_by_decorator(ipython, instance, wrap_fcn=wrap)


class ecli_magic_args(object):
    """

    """
    def __init__(self, plugin_class):
        self.plugin_class = plugin_class
        self.magic_args = magic_arguments()

    def __call__(self, fcn):
        ret = self.magic_args(fcn)
        ret.plugin_class = self.plugin_class
        return ret
