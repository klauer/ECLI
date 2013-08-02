# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util` -- Utility functions for ECLI developers
=========================================================

.. module:: ecli_util
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

import logging

def get_plugin(name='ECLICore'):
    try:
        core = get_core_plugin()
        return core.get_extension(name)
    except:
        return None

def get_core_plugin():
    try:
        return __ecli_core__
    except Exception as ex:
        print('ECLICore not loaded', ex)
        return None


def expand_alias(arg):
    core = get_core_plugin()
    if core is None:
        return arg

    try:
        return core.aliases[arg]
    except KeyError:
        if '.' in arg:
            record, field = split_record_field(arg)
            if record in core.aliases:
                return '%s.%s' % (core.aliases[record], field)
            else:
                return arg
        else:
            return arg


def generic_load_ext(ipython, ext_class, logger=None, **kwargs):
    if logger is None:
        logger = logging

    name  = ext_class.__name__
    print('Loading %s' % name)
    core = get_core_plugin()
    try:
        core.unregister_extension(name)
    except:
        pass

    if core is None:
        logger.error('ECLI core not loaded')
        return

    instance = core.register_extension(ext_class, **kwargs)
    if instance is not None:
        instance._register_callbacks()

    return instance

def generic_unload_ext(ipython, ext_class):
    core = get_core_plugin()
    if core is not None:
        return core.unregister_extension(ext_class.__name__)
    return False

from .errors import *
from .magic_args import (
    argument_count_range, argument_or_flag, arg_value_range,
    AliasedPV, export_magic_by_prefix, export_magic_by_decorator,
    export_class_magic)

from .decorators import (expand_aliases, evaluate_arguments, wrap_command)
from .epics_util import (split_record_field, is_valid_field_name, caget,
                         get_record_type, is_motor_record, is_scan_record,
                         get_motor_rbv_pv, get_motor_limits)

from .spvinfo import (get_structured_pv_info, structured_pv_info_to_list,
                      format_structured_pv_info, print_structured_pv_info)

from .misc import (
    get_column_widths, get_column_formatting_string, log_exception, get_timestamp, edit_file,
    list_management, print_traceback, fix_label, clear_line, _tests, print_table,
    print_sameline, is_valid_python_identifier, get_timestamp)

from .conditional_monitor import ConditionalMonitor
from .check import (check_bool, check_int, check_float)
from .record_info import get_record_fields
from .epics_device import (get_records_from_devices, get_record_from_device)
from .simple_table import (SimpleTable, )
