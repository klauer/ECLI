# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.misc` -- miscellaneous utilities
================================================

.. module:: ecli_util.misc
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

from __future__ import print_function
import os
import sys
import copy
import time
import datetime
import traceback
import keyword

import subprocess
import tempfile

from itertools import izip, izip_longest


from IPython.core.error import UsageError
from IPython.core.magic_arguments import (argument, magic_arguments,
                                          parse_argstring, argument_group)

from . import get_core_plugin


TYPE_TIMEOUT = 0.5


def get_column_widths(lines, maximum_width=100):
    """
    Assuming lines has the format:
        [ [item, item, ...], [item, item, ...], ... ]
    Where each line has the same number of items, and each item supports a
    conversion to string, calculate the maximum width of each column, and
    return it as a list.
    """
    lines = list(lines)
    longest = [0] * len(lines[0])
    for line in lines:
        lengths = [len(str(s)) for s in line]
        for i, (length_, longest_) in enumerate(zip(lengths, longest)):
            if length_ > longest_:
                if length_ > maximum_width:
                    longest[i] = maximum_width
                else:
                    longest[i] = length_

    return longest


def get_column_formatting_string(lines, fixed_width_format='%%-%ds',
                                 full_width_format='%s', delim='  '):
    """
    Assuming a sequence of string lists: calculate the maximum width of each
    column, and generate a format string so all lines can be printed neatly
    in a tabular format.

    Output example for 3 columns, with maximum widths of 5, 2, and 3:
        %-5s %-2s %3s
    """
    lengths = get_column_widths(lines)
    format_ = [fixed_width_format % len_ for len_ in lengths]
    if len(format_) >= 1:
        format_[-1] = full_width_format

    format_ = delim.join(format_)
    return format_


def log_exception(command=None, limit=100, filename='exceptions.log'):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    lines = traceback.format_exception(
        exc_type, exc_value, exc_traceback, limit)
    try:
        f = open(filename, 'at')
    except IOError as ex:
        print('Unable to log exception: %s' % ex)
        f = sys.stderr

    print(file=f)
    print(file=f)
    exc_typename = exc_type.__name__
    print('-- %s (%s) --' % (exc_typename, time.ctime()), file=f)
    if command is not None:
        print('Command: %s' % command, file=f)

    print('Exception: %s (%s)' % (exc_typename, exc_value), file=f)
    for line in lines:
        print(line.rstrip(), file=f)

    print('-- end --', file=f)

    if f != sys.stderr:
        f.close()


def get_timestamp():
    # TODO
    return time.time()


def edit_file(fn, editor=None):
    """
    Edit a file with the system's default editor.

    :param fn: the file to edit
    :param editor: optionally specify the editor to use
    """
    if not editor:
        if 'EDITOR' in os.environ:
            editor = os.environ['EDITOR']
        else:
            if sys.platform.startswith('win'):
                print('Opening with the default associated editor')
                editor = 'start'
            elif sys.platform.startswith('mac`'):
                print('Opening with the default associated editor')
                editor = 'open'
            else:
                print('Set the EDITOR environment variable \
                      or specify an editor', file=sys.stderr)
                return

    cmd = '%s "%s"' % (editor, fn)
    ret = -1
    try:
        ret = subprocess.call(cmd, shell=True)
    except Exception as ex:
        print('Unable to spawn process: (%s) %s (ret=%d)' %
             (ex.__class__.__name__, ex, ret))
        return False
    else:
        return (ret == 0)


# TODO: this needs to be updated and/or removed
def list_management(type_=str, get_list=None, set_list=None, add_function=None,
                    remove_function=None):
    @magic_arguments()
    @argument_group('Add/remove')
    @argument('-a', '--add', type=type_, help='Add entries.')
    @argument('-r', '--remove', type=type_, help='Remove entries.')
    @argument('-n', '--index', type=int,
              help='Index to use for insertion or deletion')
    @argument_group('Full list operations')
    @argument('-c', '--clear', nargs='?', const=1, help='Clear the list.')
    @argument('-l', '--load', metavar='file', type=unicode,
              help='Load (merge) the list from a file.')
    @argument('-s', '--save', metavar='file', type=unicode,
              help='Save the list to a file.')
    @argument_group('External editor')
    @argument('-e', '--edit', nargs='?', const='', type=unicode,
              help='Edit in the default editor (or specify the one to use).')
    def _list_management(self, arg):
        """
        """
        def load_list(fn):
            try:
                new_list = open(fn, 'rt').readlines()
            except Exception as ex:
                print('Failed to load file: %s' % ex)
                return

            return [type_(item.strip()) for item in new_list]

        def save_list(fn):
            try:
                f = open(fn, 'wt')
            except Exception as ex:
                print('Failed to open file: %s' % ex)
                return

            # f.write('\n'.join([unicode(s).encode('utf-8') for s in list_]))
            f.write('\n'.join([str(s) for s in list_]))

        def display_list(list_=None):
            if list_ is None:
                list_ = get_list()
            for i, item in enumerate(list_):
                if item:
                    print(' %2d.) %s' % (i + 1, item))

        if not arg.strip():
            display_list()
            return

        args = parse_argstring(_list_management, arg)
        list_ = get_list()
        modified = False

        if args.clear:
            list_ = []
            modified = True

        if args.add is not None:
            if args.add not in list_:
                modified = True
                print('Adding %s' % args.add)
                if add_function is not None:
                    add_function(args.add, index=args.index)
                else:
                    if args.index is not None:
                        if args.index < 0 or args.index > len(list_):
                            raise UsageError('Invalid index')
                        list_.insert(args.index, args.add)
                    else:
                        list_.append(args.add)

        if args.remove is not None:
            if args.remove in list_ or args.index is not None:
                modified = True
                if remove_function is not None:
                    remove_function(args.remove, index=args.index)
                else:
                    if args.index is not None:
                        if args.index < 0 or args.index >= len(list_):
                            raise UsageError('Invalid index')
                        print('Removing %s' % list_[args.index])
                        list_.pop(args.index)
                    else:
                        print('Removing %s' % args.remove)
                        list_.remove(args.remove)

        if args.load is not None:
            fn = args.load
            new_list = load_list(fn)
            if new_list is not None:
                to_add = set(new_list) - set(list_)

                print('List loaded from: %s' % fn)
                if add_function is not None:
                    for add_ in to_add:
                        add_function(add_)

                else:
                    list_.extend([item for item in sorted(to_add,
                                                          key=lambda item: new_list.index(item))])

                modified = True

        if args.save is not None:
            save_list(args.save)
            print('List saved to: %s' % args.save)

        if args.edit is not None:
            f = tempfile.NamedTemporaryFile()
            with f:
                save_list(f.name)
                if not edit_file(f.name, args.edit):
                    print('File editing cancelled; contents not loaded')
                else:
                    new_list = load_list(f.name)
                    if new_list is not None:
                        print('List loaded from: %s' % f.name)
                        if add_function is not None:
                            to_add = set(new_list) - set(list_)
                            to_remove = set(list_) - set(new_list)
                            for rem_ in to_remove:
                                remove_function(rem_)
                            for add_ in sorted(to_add, key=lambda item:
                                               new_list.index(item)):
                                add_function(add_)
                        else:
                            list_ = new_list

                        # TODO: win32 wait for return
                        modified = True
                        display_list(list_)

        if modified and add_function is None:
            set_list(list_)

    return _list_management


def print_traceback(ex=None, f=sys.stderr):
    """
    Dump a text traceback from the last exception to the file
    specified

    :param ex: the exception to print
    :param f: the file to dump to
    """
    # TODO this uses the last exception, not the one passed
    exc_type, exc_value, exc_traceback = sys.exc_info()
    lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    print('Exception:', file=f)
    for line in lines:
        print(line.rstrip(), file=f)


class OutputStreamHandler(object):
    """
    Redirects an output stream to a callback functions
    """
    def __init__(self, write_fcn=None, flush_fcn=None):
        """
        :param write_fcn: this function is called when the stream is written to
        :type write_fcn: function or None (ignored)
        :param flush_fcn: this function is called when the stream is flushed
        :type flush_fcn: function or None (ignored)
        """
        self.write_fcn = write_fcn
        self.flush_fcn = flush_fcn

    def write(self, s):
        if self.write_fcn is not None:
            self.write_fcn(s)

    def flush(self):
        if self.flush_fcn is not None:
            self.flush_fcn()


def fix_label(label):
    """
    No spaces for SPS 'axistitles'
    No commas for SPS 'plotlist'
    """
    return unicode(label.replace(' ', '_').replace(',', '_'))


def clear_line():
    """
    Clear the current line of text on the terminal.
    """
    # TODO determine terminal width, type, or at least something
    # more intelligent... though this is probably safest:
    print(''.join(('\r', ' ' * 50, '\r')), end='')

    # if sys.platform in ('win32', ):
    #    print(''.join(('\r', ' ' * 50, '\r')), end='')
    # else:
    # Assume VT-100
    #    print('\r\x1b[K', end='')


def print_sameline(*args, **kwargs):
    """
    Print text on the same line (same arguments as the Python print function)
    """
    clear_line()

    if 'end' in kwargs:
        print(*args, **kwargs)
    else:
        print(*args, end='', **kwargs)

    if 'file' in kwargs:
        kwargs['file'].flush()
    else:
        sys.stdout.flush()


def _tests():
    '''
    %run -i ecli_util
    '''


def remove_columns(table, remove_columns, in_place=False):
    """
    From a list of rows, remove columns by index

    :param rows: the rows
    :param remove_columns: the column indices to remove
    :param in_place: if in-place, the list will be modified
    """
    if not in_place:
        table = copy.deepcopy(table)

    col_offset = 0
    for i in remove_columns:
        for row in table:
            del row[i - col_offset]
        col_offset += 1

    return table


def remove_empty_columns(rows, in_place=False):
    '''
    From a list of rows, remove empty columns.

    :param rows: the rows
    :param in_place: if in-place, the list will be modified
    '''
    remove_cols = []
    for i, col in enumerate(izip(*rows)):
        col = list(col)
        if set(col[1:]) == set(['']):
            remove_cols.append(i)

    if remove_cols:
        return remove_columns(rows, remove_cols, in_place=in_place)

    return rows


def print_table(rows, min_col_width=5, format_str=u'{:>%d}', f=sys.stdout,
                delimiter=u' ', first_column_format=None, remove_empty=True):
    '''
    Not to be confused with the SimpleTable class, this prints out a table
    stored as a list of lists::

        [['row1, 1', 'row1, 2', '...'], ['row2', ...'], ...]

    :param rows: the rows
    :param min_col_width: minimum column width (spaces)
    :param format_str: the format string to use with str.format()
                       defaults to right-aligned columns
    :param f: the file/stream to output to (requires write method)
    :param delimeter: the delimeter to print between columns
    :param first_column_format: the first column can optionally
                                have a different format
    :param remove_empty: remove empty columns first
    :return: the printed rows
    '''
    if not rows:
        return

    if remove_empty:
        rows = remove_empty_columns(rows)

    cols_combined = list(izip_longest(*rows, fillvalue=u''))

    lengths = []

    def longest_entry(col):
        len_ = max(len(c) for c in col)
        len_ = max(min_col_width, len_)
        return len_

    lengths = [longest_entry(col) for col in cols_combined]

    if first_column_format is not None:
        format_ = [first_column_format % lengths[0]]
        format_.extend([format_str % len_ for len_ in lengths[1:]])
    else:
        format_ = [format_str % len_ for len_ in lengths]

    for row in rows:
        row_format = delimiter.join(format_[:len(row)])
        print(row_format.format(*row), file=f)

    return rows

import csv


def load_csv_header(fname, main_col='field', delimiter='\t'):
    '''
    Expects a (tab) delimited file with the first row being a header (column names)
    Lines starting with # are ignored (after the first row)
    Raises ValueError if main column not present

    For example::

        Field\tname1\tname2
        field_1\tvalue1\tvalue2
        ...

    Returns a dictionary::

        { 'field_1' : { 'name1' : 'value1', 'name2' : 'value2', ... }, ... }
    '''
    with open(fname, mode='rb') as f:
        reader = csv.reader(f, dialect='excel', delimiter=delimiter)
        columns = [s.lower() for s in reader.next()]
        column_idx = dict((s.lower(), columns.index(s)) for s in columns)
        if main_col not in column_idx:
            raise ValueError('Column "%s" not present' % main_col)

        info = {}
        for line in reader:
            if line and line[0].startswith('#'):
                continue

            info_dict = dict(zip(columns, line))
            try:
                field = info_dict[main_col]
            except KeyError:
                raise
            else:
                if field:
                    del info_dict[main_col]
                    info[field] = info_dict

        return columns, info


def is_valid_python_identifier(name):
    return name not in keyword.kwlist

def get_timestamp(dt=None):
    if dt is None:
        dt = datetime.datetime.now()

    plugin = get_core_plugin()
    return dt.strftime(plugin.date_format)

if __name__ == '__main__':
    _tests()
