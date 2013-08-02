# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.spvinfo` -- Structured PV info
===================================================

.. module:: ecli_util.spvinfo
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

.. note:: (TODO) this needs to be converted to a SimpleTable someday
"""
from __future__ import print_function
import sys
import time
import epics
import logging

from . import expand_alias

from .misc import print_table
from .errors import TimeoutError

# TODO convert this to the SimpleTable thing eventually
def get_structured_pv_info(dict_, prefix='', timeout=None, t_start=None,
                           fail_on_error=False):
    '''
    For a dictionary like the following with a prefix of 'PV'::

        get_structured_pv_info(
            { 'User' : {
                'High' : '.HLM',
                'Current' : '.RBV',
                'Low' : '.LLM',
                 } ,
            }, prefix='PV')

    The result would look like::

        {
            'User' : {
                'High' : 2.0,     # <-- caget PV.HLM = 2.0
                'Current' : 1.0,  # <-- caget PV.RBV = 1.0
                'Low' : 0.0,      # <-- caget PV.RBV = 0.0
             } ,
        }

    `prefix` can also be a list (or sequence), and the result would then be::

        return {
                'User' : {
                    'High' : [1, 2, 3, ...]
                         }
               }
    '''
    if t_start is None:
        t_start = time.time()

    args = dict(prefix=prefix, t_start=t_start, timeout=timeout,
                fail_on_error=fail_on_error)

    ret = {}
    for key, value in dict_.iteritems():
        if timeout is not None:
            if time.time() - t_start > timeout:
                raise TimeoutError()

        if isinstance(value, dict):
            ret[key] = get_structured_pv_info(value, **args)
        else:
            if isinstance(prefix, (list, tuple)):
                ret[key] = [None] * len(prefix)
                for i, p in enumerate(prefix):
                    try:
                        ret[key][i] = epics.caget(
                            expand_alias('%s%s' % (p, value)))
                    except Exception as ex:
                        logging.debug('caget error: (%s) %s' % (
                            ex.__class__.__name__, ex))
                        print('caget error: (%s) %s' % (
                            ex.__class__.__name__, ex))
                        if fail_on_error:
                            raise
            else:
                try:
                    ret[key] = epics.caget(expand_alias(
                        '%s%s' % (prefix, value)))
                except:
                    if fail_on_error:
                        raise
                    else:
                        ret[key] = None

    return ret


def structured_pv_info_to_list(d, level=0):
    for key, value in sorted(d.iteritems()):
        if isinstance(value, dict):
            yield level, key, None
            for l, k, v in structured_pv_info_to_list(value, level + 1):
                yield l, k, v
        else:
            yield level, key, value


def format_structured_pv_info(d, level_indent=u' ', format_=u'%.4g',
                              value_delimiter=u' ', column_headers=[]):
    '''
    Format the pv info from get_structured_pv_info(), for usage with print_table
    '''
    def format_value(v):
        try:
            return format_ % v
        except:
            return u'%s' % v

    def row_label(level, key):
        return u'%s%s' % (level_indent * level, format_value(key))

    def get_row(level, key, value):
        row = [row_label(level, key)]
        if isinstance(value, (list, tuple)):
            row.extend([format_value(v) if v is not None else u''
                        for v in value])
        elif value is None:
            row.extend([u''])
        else:
            row.extend([format_value(value)])

        return row

    if column_headers:
        yield get_row(0, column_headers[0], column_headers[1:])

    for level, key, value in structured_pv_info_to_list(d):
        yield get_row(level, key, value)


def print_structured_pv_info(d, first_column_format=u'{:<%d}', f=sys.stdout, **kwargs):
    '''
    Print the structured pv info in a table
    '''
    rows = list(format_structured_pv_info(d))
    print_table(rows, first_column_format=first_column_format,
                f=sys.stdout, **kwargs)


def _test():
    d = {
        'one': {'pv1': 'p0', 'pv2': 'p0'},
        'two': {'pv3': 'p0', 'pv4': 'p0'},
        'three': {'pv3': 'p0', 'four': {'pv5': 'p0'}},
    }

    from . import print_table
    ret = get_structured_pv_info(d, prefix=['MTEST:', 'MTEST:', 'MTEST:'])
    rows = list(
        format_structured_pv_info(ret, column_headers=['', '1', '2', '3']))
    print_table(rows, first_column_format=u'{:<%d}',)
