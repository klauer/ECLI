# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.simple_table`
=============================

.. module:: ecli_util.simple_table
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import sys
import copy
import StringIO

# TODO should probably replace this with something common
#       and why not just store by column index and optionally reference
#       them by label? ...


class SimpleTable(object):
    """
    A simple, inefficient representation of a table, where data is stored by
    column. Column header text must be unique.
    """
    def __init__(self, headers=[], empty=''):
        self.headers = headers
        self._rows = 0
        self._empty = empty

    def _get_headers(self):
        return list(self._headers)

    def _set_headers(self, headers):
        if len(set(headers)) != len(headers):
            raise ValueError('Duplicate header(s) -- must be unique')

        self._headers = list(headers)
        self._data = dict((header, []) for header in self._headers)
        self._rows = 0

    headers = property(_get_headers, _set_headers,
                       doc='The column headers [list]')

    def __copy__(self):
        table = SimpleTable(headers=self.headers, empty=self._empty)
        table._data = copy.deepcopy(self._data)
        table._rows = self._rows
        return table

    @staticmethod
    def from_rows(rows, headers=None, **kwargs):
        """
        (static method)
        Create a SimpleTable from row data

        :param rows: the row data
        :param headers: the headers (if None, the first row is used)
        kwargs are passed onto the table constructor
        """
        if headers is None:
            headers = rows[0]
            rows = rows[1:]

        table = SimpleTable(headers, **kwargs)
        for row in rows:
            table.add_row(row)
        return table

    @staticmethod
    def from_columns(columns, headers=None, **kwargs):
        """
        (static method)
        Create a SimpleTable from column data

        :param columns: the column data
        :param headers: the headers (if None, the first entry of each
                        column is used)
        kwargs are passed onto the table constructor
        """
        if headers is None:
            headers = [col[0] for col in columns]
            columns = [col[1:] for col in columns]

        if len(columns) != len(headers):
            raise ValueError('Each column must have a header')

        row_counts = set([len(col) for col in columns])
        if len(row_counts) > 1:
            raise ValueError('All columns must be the same length')

        table = SimpleTable(**kwargs)
        table._rows = list(row_counts)[0]
        for header, column in zip(headers, columns):
            table.add_column(header, fill=column)

        return table

    def insert_row(self, row, index=None):
        """
        Insert a row at a specific index (default is to append)

        :param row: the row data
        :param index: the index to insert before
        """
        assert(len(row) == len(self._headers))

        for header, cell in zip(self._headers, row):
            if index is None:
                self._data[header].append(cell)
            else:
                self._data[header].insert(index, cell)
        self._rows += 1

    add_row = insert_row

    def get_rows(self, skip_columns=None):
        """
        All of the row data, including the header row
        """
        def skip(list_):
            if skip_columns is None:
                return list_
            else:
                return [value for i, value in enumerate(list_)
                        if i not in skip_columns]

        yield skip(self._headers)
        data = [self._data[header] for header in self._headers]
        for row in zip(*data):
            yield skip(row)

    @property
    def rows(self):
        """
        All of the row data, including the header row
        """
        for row in self.get_rows():
            yield row

    def column_index(self, header):
        """Get the index of a column header in the table"""
        return self._headers.index(header)

    def column_indices(self, headers):
        """Get the indices of column headers in the table"""
        return [self.column_index(header) for header in headers]

    def remove_row(self, idx):
        """Remove a row by index"""
        assert(0 < idx < self._rows)

        idx -= 1  # 0 is for the header
        for col in self._data.values():
            del col[idx]

        self._rows -= 1

    def remove_column_by_index(self, idx):
        """Remove a column by index"""
        header = self._headers[idx]
        del self._headers[idx]
        del self._data[header]

    def remove_columns_by_index(self, indices):
        """Remove multiple columns by index"""
        i = 0
        for idx in sorted(indices):
            self.remove_column_by_index(idx - i)
            i += 1

    def add_column(self, header, index=None, fill=None):
        """
        Add a column with a `header` before `index` in the table,
        filling its contents with `fill`.

        :param header: the column header label
        :param index: the column index to insert before
        :param fill: the data to fill the column with (list or string)
        """
        if fill is None:
            fill = self._empty

        if header in self._headers:
            raise ValueError('Duplicate header')

        if index is None:
            self._headers.append(header)
        else:
            self._headers.insert(index, header)

        if isinstance(fill, (list, tuple)):
            assert(len(fill) == self._rows)
            self._data[header] = list(fill)
        else:
            self._data[header] = [fill] * self._rows

    @property
    def column_and_index(self):
        for i, header in enumerate(self._headers):
            yield i, header, self._data[header]

    def columns(self, include_headers=True, include_empty=True):
        """
        (generator)
        Gives all columns in the table, optionally including headers
        or removing empty columns.

        :param include_headers: include column headers
        :param include_empty: include empty columns in the result
        """
        for i, header in enumerate(self._headers):
            col = self._data[header]
            if not include_empty and set(col) == set([self._empty]):
                continue

            if include_headers:
                yield [header] + col
            else:
                yield col

    def remove_empty_columns(self):
        """
        Remove all empty columns
        """
        indices = [i for i, header, col in self.column_and_index
                   if set(col) == set([self._empty])]

        self.remove_columns_by_index(indices)

    def print_(self, min_col_width=5, format_str=u'{:>%d}', f=sys.stdout,
               delimiter=u' ', first_column_format=None, include_empty=False):
        """
        Print the table to a stream (default: stdout) with a specific format

        :param min_col_width: minimum column width (spaces)
        :param format_str: the format string to use with str.format()
                           defaults to right-aligned columns
        :param f: the file/stream to output to (requires write method)
        :param delimeter: the delimeter to print between columns
        :param first_column_format: the first column can optionally
                                    have a different format
        :param include_empty: display empty columns
        """
        lengths = []

        def longest_entry(col):
            len_ = max(len(c) for c in col)
            len_ = max(min_col_width, len_)
            return len_

        cols = list(self.columns(include_headers=True, include_empty=include_empty))
        lengths = [longest_entry(col) for col in cols]

        if first_column_format is not None:
            format_ = [first_column_format % lengths[0]]
            format_.extend([format_str % len_ for len_ in lengths[1:]])
        else:
            format_ = [format_str % len_ for len_ in lengths]

        format_ = delimiter.join(format_)

        headers = [col[0] for col in cols]
        empty_columns = set(self._headers) - set(headers)
        empty_idx = [self._headers.index(header) for header in empty_columns]
        for i, row in enumerate(self.get_rows(skip_columns=empty_idx)):
            print(format_.format(*row), file=f)

    def __getitem__(self, key):
        """
        Access the table by table[col, row]
        """

        col, row = key
        if col not in self._headers:
            col = self._headers[col]

        if row == 0:
            return col
        else:
            return self._data[col][row - 1]

    def __setitem__(self, key, value):
        """
        Modify the table by table[col, row] = value
        """
        col, row = key
        if row == 0:
            if col in self._headers:
                col = self._headers.index(col)

            if value in self._headers:
                raise KeyError('Header already exists')

            old_header = self._headers[col]
            self._headers[col] = value
            self._data[value] = self._data[old_header]
            del self._data[old_header]
        else:
            if col not in self._headers:
                col = self._headers[col]

            self._data[col][row - 1] = value

    def __str__(self):
        s = StringIO.StringIO()  # not Python 3 compatible
        self.print_(f=s)
        return s.getvalue()

    __iter__ = rows

if __name__ == '__main__':
    table = SimpleTable()
    table.headers = ['aa aa aa', 'b', 'c', 'empty']
    table.add_row(['one', '1', 'one', ''])
    table.add_row(['two', '2', 'two', ''])
    table.add_row(['three', '3', 'three', ''])
    table.add_column('fourth non-empty col', fill=['x', 'x', 'x'])

    print('headers', table.headers)
    print('all rows', list(table.rows))
    table.print_(include_empty=False)
    assert(table['b', 0] == 'b')
    assert(table[1, 0] == 'b')
    table['b', 0] = 'newone'
    table['newone', 1] = '2'

    print(table)
    assert(table[1, 0] == 'newone')

    for i in range(5):
        print('---', i)
        #table.remove_row(1)
        table.remove_column_by_index(0)
        table.print_(include_empty=False, delimiter='|')
