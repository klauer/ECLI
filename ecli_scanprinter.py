# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_scanprinter` -- Scan printer ECLI extension
======================================================

.. module:: ecli_scanprinter
    :synopsis: Prints scan information as it comes in from :mod:`ecli_stepscan`.
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

from __future__ import print_function
import sys
import time
import logging
import itertools
from itertools import izip

import numpy as np

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_plugin import ECLIPlugin

SCAN_PLUGIN = 'ECLIScans'
logger = logging.getLogger('ECLI.ScanPrinter')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScanPrinter, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    # TODO stop any monitors, etc.
    return util.generic_unload_ext(ipython, ECLIScanPrinter)


class ECLIScanPrinter(ECLIPlugin):
    VERSION = 1
    REQUIRES = [('ECLICore', 1), (SCAN_PLUGIN, 1)]

    if 1:
        # TODO: IPython.zmq.iostream.OutStream(object) is not a file
        outfile = traitlets.Instance(object, config=True)
    else:
        outfile = traitlets.Instance(file, config=True)
    format_string = traitlets.Unicode(u'%g', config=True)
    min_col_width = traitlets.Integer(5, config=True)
    reprint_headers = traitlets.Bool(True, config=True)
    reprint_points = traitlets.Integer(30, config=True)
    blank_before_headers = traitlets.Bool(True, config=True)
    show_overhead = traitlets.Bool(True, config=True)
    show_elapsed = traitlets.Bool(True, config=True)
    pv_header = traitlets.Bool(False, config=True)
    show_grid_point = traitlets.Bool(True, config=True)

    def __init__(self, shell, config):
        super(ECLIScanPrinter, self).__init__(shell=shell, config=config)
        if self.outfile is None:
            self.outfile = sys.stdout

        logger.info('ECLI Scan printer writing to: file=%s' % self.outfile)
        self._scan_number = 0
        self._last_point = None

        scan_plugin = get_plugin(SCAN_PLUGIN)
        self.add_callback(scan_plugin.CB_PRE_SCAN, self.pre_scan,
                          extension=SCAN_PLUGIN)
        self.add_callback(scan_plugin.CB_POST_SCAN, self.post_scan,
                          extension=SCAN_PLUGIN)
        self.add_callback(scan_plugin.CB_SCAN_STEP, self.single_step,
                          extension=SCAN_PLUGIN)

    @property
    def logger(self):
        return logger

    def _format_header(self, header, width):
        return util.fix_label(header).rjust(width)

    def pre_scan(self, scan=None, scan_number=0, mca_detectors=[], **kwargs):
        self.t_start = time.time()

        print('--- Scan %d ---' % (scan_number, ), file=self.outfile)
        counters = [c for c in scan.counters
                    if c not in mca_detectors]
        self._headers = ['Point', 'Timestamp']

        if self.pv_header:
            self._headers += [c.pv.pvname for c in counters]
        else:
            self._headers += [c.label for c in counters]

        self._header_widths = [max(self.min_col_width, len(header))
                               for header in self._headers]

    def _print_headers(self, column_widths=[]):
        if not column_widths:
            column_widths = [self.min_col_width] * len(self._headers)

        cols = ' '.join([self._format_header(s, w)
                         for s, w in zip(self._headers, column_widths)])
        print(cols, file=self.outfile)

    def post_scan(self, scan=None, abort=False, **kwargs):
        self.t_finished = time.time()
        self.t_elapsed = self.t_finished - self.t_start

        if self.show_elapsed:
            print('Scan finished (elapsed %.2fs)' %
                  (self.t_elapsed, ), file=self.outfile)

        if self._last_point is not None and self.show_overhead:
            dwell_time = scan.dwelltime
            elapsed = self.t_elapsed
            npts = self._last_point
            estimated = npts * dwell_time
            move_time = scan.positioners[0].move_time
            print('\t--- Statistics:', file=self.outfile)
            print('\tEstimated: %.3f' % (estimated, ), file=self.outfile)
            print('\tPer point %.3f overhead %.3f per point overhead %.3f' %
                  (elapsed / npts, (elapsed - estimated),
                  (elapsed - estimated) / npts),
                  file=self.outfile)

            print('\tExcluding move time (%.3f):' %
                  move_time, file=self.outfile)
            elapsed -= move_time
            print('\tPer point %.3f overhead %.3f per point overhead %.3f' %
                  (elapsed / npts, (elapsed - estimated),
                  (elapsed - estimated) / npts),
                  file=self.outfile)

    def single_step(self, scan=None, grid_point=(), point=0, array_idx=0,
                    **kwargs):
        self._last_point = point
        data = [c.buff[array_idx] for c in scan.counters]

        def format_scaler_data(d):
            try:
                return self.format_string % d
            except:
                return str(d)

        scaler_data = [format_scaler_data(d) for d in data
                       if not isinstance(d, np.ndarray)]

        def grid_string(point, dimensions, delim=','):
            ret = []
            for pt, dim in zip(point, dimensions):
                dlen = len(str(dim))
                dformat = '%%.%dd' % (dlen, )
                ret.append(dformat % pt)
            return delim.join(ret)

        ndim = scan.ecli_info['ndim']
        dims = scan.ecli_info['dimensions']
        if ndim > 1 and self.show_grid_point:
            point_str = grid_string(grid_point, dims)
        else:
            point_str = u'%d' % point

        data_str = [point_str, util.get_timestamp()]
        data_str.extend(scaler_data)

        header_widths = self._header_widths  # modified in-place

        # Ensure that none of the columns have changed size (such that
        # a printed value would be longer than its header field)
        longer_indices = [i for i, len_, value
                          in (izip(itertools.count(), header_widths, data_str))
                          if len(value) > len_]

        lengths_changed = False
        for index in longer_indices:
            header_widths[index] = len(data_str[index]) + 2
            lengths_changed = True

        # Re-print out the header if necessary
        if lengths_changed or (point % self.reprint_points) == 0:
            if point == 0 or self.reprint_headers:
                if self.blank_before_headers:
                    print(u'', file=self.outfile)
                self._print_headers(header_widths)

        # Right justify all of the values, and print them out
        data_str = [value.rjust(len_)
                    for len_, value in zip(header_widths, data_str)]
        print(u' '.join(data_str), file=self.outfile)
