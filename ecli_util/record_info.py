# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.record_info` -- EPICS record information
========================================================

.. module:: ecli_util.record_info
    :synopsis: Manages record field information, loaded from tab-delimited
               text files in records/*.txt (which were distilled from dbd
               files originally)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""
from __future__ import print_function
import os
from .misc import load_csv_header

PATH = os.path.dirname(os.path.abspath(__file__))
RECORD_PATH = os.path.join(PATH, 'records')
_field_cache = {}


class RecordFields(object):
    """
    Inefficiently manages record field information, loaded from text files
    located in records/*.txt (relative to this file)
    """
    # TODO could easily toss in a db, but it's just so much nicer having simple
    # text files
    main_columns = ['field']

    def __init__(self, rtyp=None, fn=None):
        if rtyp is not None:
            self._filename = os.path.join(RECORD_PATH, '%s.txt' % rtyp)
        else:
            assert(fn is not None)
            self._filename = fn

        name_col = self.main_columns[0]
        loaded = load_csv_header(self._filename, main_col=name_col)
        self._columns, self._info = loaded
        self._columns.remove(name_col)
        self.descriptions = self.generate_dict('prompt')

    @property
    def fields(self):
        return self._info.keys()

    def find(self, text, columns=None, case_sensitive=False):
        '''
        Find "text" in any column or field name
        '''
        # Not an efficient implementation, so this should be used infrequently --
        # but only real use case I can see is users grepping the list to find a
        # field
        if not case_sensitive:
            text = text.lower()

        for name, info in self._get_columns(columns=columns, fill_value=''):
            all_text = '%s %s' % (name, info)
            if not case_sensitive:
                all_text = all_text.lower()

            if text in all_text:
                yield name, info

    @property
    def columns(self):
        return tuple(self._columns)

    def _get_columns(self, columns=None, fill_value=None):
        if columns is None:
            columns = self._columns

        if isinstance(columns, (list, tuple)):
            for name, info in self._info.iteritems():
                yield name, [info[col] if col in info
                             else fill_value
                             for col in columns]
        else:
            col = columns
            for name, info in self._info.iteritems():
                try:
                    yield name, info[col]
                except KeyError:
                    yield name, fill_value

    def generate_dict(self, columns, fill_value=None):
        '''
        From the detailed information in the database,
        return a simplified one containing only the main
        keys and the specified field(s).

        If one field is specified, the result is:
            { 'field' : 'value' }
        Otherwise, it's a list in the same order as 'columns':
            { 'field' : ['value1', 'value2'] }
        '''
        return dict(self._get_columns(columns, fill_value=fill_value))


def get_record_fields(rtyp):
    """
    Get the RecordFields instance associated with the specific
    record type (rtyp) -- e.g., 'motor' or 'ai'

    .. note:: As the RecordFields instances are cached, users should use this
              function instead of instantiating their own.
    """
    if rtyp not in _field_cache:
        _field_cache[rtyp] = RecordFields(rtyp=rtyp)

    return _field_cache[rtyp]


def _test():
    # load_csv_header('%s/motor.csv' % RECORD_PATH)
    # rf = RecordFields('motor')
    # print(rf.descriptions)
    for fn in os.listdir(RECORD_PATH):
        if fn.endswith('.txt'):
            path, fn = os.path.split(fn)
            fn, ext = os.path.splitext(fn)
            print('--', fn)
            rf = RecordFields(fn)

            print(list(rf.find('used')))

if __name__ == '__main__':
    _test()
