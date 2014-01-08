# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_scanwriter_hdf5` -- HDF5 scan writer
===============================================

.. module:: ecli_scanwriter_hdf5
    :synopsis: ECLI HDF5 file writer for scans (:mod:`ecli_stepscan`)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
.. note:: requires h5py <http://www.h5py.org> >= 2.2.0
"""

from __future__ import print_function
import os
import logging
import numpy as np
import datetime
import time

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import get_plugin

import h5py

logger = logging.getLogger('ECLI.ScanWriterHDF5')

if h5py.version.version < '2.2.0':
    logger.warning('h5py version may be incompatible (recommended version is 2.2.0+)')

SCAN_PLUGIN = 'Scans'


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScanWriterHDF5, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScanWriterHDF5)


def parse_scan_key(key):
    # 'Scan_0005' -> 5
    scan, number = key.split('_', 1)
    return int(number)


class ECLIScanWriterHDF5(ECLIPlugin):
    """
    ECLI HDF5 file writer for scans
    """
    VERSION = 1
    SCAN_PLUGIN = 'ECLIScans'
    REQUIRES = [('ECLICore', 1), (SCAN_PLUGIN, 1)]

    filename = traitlets.Unicode(u'', config=True)
    _callbacks = []

    def __init__(self, shell, config):
        super(ECLIScanWriterHDF5, self).__init__(shell=shell, config=config)
        logger.info('Initializing ECLI HDF5 file writer plugin')
        self._scan_number = 0
        self._scans_group = None  # Group for all scans
        self._scan_group = None  # Group for single scan (under scans_group)
        self._open_file(self.filename)

        scan_plugin = get_plugin(self.SCAN_PLUGIN)
        callbacks = [(scan_plugin.CB_PRE_SCAN,  self.pre_scan),
                     (scan_plugin.CB_POST_SCAN, self.post_scan),
                     (scan_plugin.CB_SCAN_STEP, self.single_step),
                     (scan_plugin.CB_SAVE_PATH, self.save_path_set),
                     ]

        self.scan_plugin = scan_plugin

        for cb_name, fcn in callbacks:
            scan_plugin.add_callback(cb_name, fcn)

    @property
    def logger(self):
        return logger

    def _new_scan(self, scan_number, overwrite=False):
        """
        Setup the HDF5 scan group for the new scan number
        """
        group_name = 'Scan_%.4d' % (scan_number, )
        logger.debug('New group name %s' % group_name)
        try:
            group = self._scans_group.create_group(group_name)
        except ValueError:
            if overwrite:
                group = self._scans_group[group_name]
                logger.debug('Existing group: %s' % group)
                return group
            else:
                return None

        logger.debug('Created group: %s' % group)
        return group

    @property
    def last_scan_number(self):
        """
        If a file is loaded, return the last (integral) scan ID
        """
        if self._scans_group is None:
            return 0

        keys = [parse_scan_key(key) for key in self._scans_group]

        if keys:
            return max(keys)
        else:
            return 0

    def _open_file(self, filename):
        self._file = None
        self._scan_group = None
        self._scans_group = None
        if not filename:
            return

        new_file = not os.path.exists(filename)
        if new_file:
            write_mode = 'w'
        else:
            write_mode = 'a'

        try:
            self._file = h5py.File(filename, write_mode, libver='latest')
        except Exception as ex:
            logger.error('Unable to use HDF5 file "%s": (%s) %s' %
                         (self.filename, ex.__class__.__name__, ex))
            logger.debug('HDF5 open error "%s"' % (self.filename, ),
                         exc_info=True)

            self.filename = None
            self._file = None
            return False

        else:
            logger.info('Opened %s' % self._file)
            self.filename = filename
            self._scans_group = self._file.require_group('Scans')
            self.scan_plugin.set_min_scan_number(self.last_scan_number + 1)
            logger.debug('Last scan number: %d' % self.last_scan_number)
            return True

    def pre_scan(self, scan=None, scan_number=0, command='', dimensions=(), **kwargs):
        """
        Callback: called before a scan starts
        """
        if self._file is None:
            logger.error('HDF5 file not set; scan will not be saved. (See: `%%scan_save` or %%config %s)' %
                         (self.__class__.__name__, ))
            return

        self._scan_number = scan_number
        self._file._comment = scan.comments
        extra_pv_info = scan.read_extra_pvs()

        self._scan_group = sgroup = self._new_scan(scan_number)
        # Attributes under the scan group:
        sgroup.attrs['number'] = scan_number
        sgroup.attrs['command'] = command
        sgroup.attrs['dwell_time'] = scan.dwelltime
        sgroup.attrs['start_timestamp'] = time.time()
        sgroup.attrs['dimensions'] = tuple(dimensions)

        # Record all of the pre-scan values (e.g., motor positions not being
        # scanned)
        pre_scan_group = sgroup.require_group('pre-scan')
        for desc, pvname, value in extra_pv_info:
            pre_scan_group.attrs[desc] = value

        # Show a mapping of the PV description/alias to actual PV name
        pv_info = sgroup.require_group('pv_info')
        for desc, pvname, value in extra_pv_info:
            pv_info.attrs[desc] = pvname

        # Additionally, record the counter labels:
        for c in scan.counters:
            label = util.fix_label(c.label)
            pv_info.attrs[label] = c.pv.pvname

    def post_scan(self, scan=None, abort=False, **kwargs):
        """
        Callback: called after a scan finishes
        """
        if self._scan_group is None:
            return

        scan_group = self._scan_group
        scan_group.attrs['end_timestamp'] = time.time()

        end = scan_group.attrs['end_timestamp']
        start = scan_group.attrs['start_timestamp']
        if isinstance(start, datetime.datetime):
            end = datetime.datetime.strptime(end, self.core.date_format)
            start = datetime.datetime.strptime(start, self.core.date_format)
            scan_group.attrs['elapsed'] = (end - start).total_seconds()
        else:
            scan_group.attrs['elapsed'] = end - start

    def single_step(self, scan=None, grid_point=(), point=0, array_idx=0,
                    timestamps=None, **kwargs):
        """
        Callback: called after every single point in a stepscan
        """
        if self._file is None or self._scan_group is None:
            return

        scan_group = self._scan_group
        dimensions = scan_group.attrs['dimensions']

        # Create the data group if necessary
        data_group = scan_group.require_group('Data')

        data_sets = [(counter.label, counter.buff[array_idx])
                     for counter in scan.counters]

        if timestamps is not None:
            data_sets.append(('Timestamps', timestamps[array_idx]))

        for label, data in data_sets:
            label = util.fix_label(label)
            if data is None:
                continue

            # Create the array in the data group if it doesn't already exist
            if label not in data_group:
                shape = list(dimensions) + list(np.shape(data))
                try:
                    dtype = np.dtype(data)
                except TypeError:
                    dtype = data.__class__
                dataset = data_group.require_dataset(label,
                                                     shape=shape, dtype=dtype)
            else:
                dataset = data_group[label]

            # And update the HDF5 dataset with the new data
            try:
                if len(grid_point) == len(dataset.shape) and len(grid_point) > 1:
                    dataset[grid_point] = data
                else:
                    dataset[array_idx] = data
            except:
                logger.error(u'Error updating dataset', exc_info=True)

        # TODO link to external files for additional detectors

    def _filename_changed(self, name, old, new):
        self._open_file(new)

    def save_path_set(self, path=None):
        """
        Callback: global save file path has changed
        """
        self.filename = u'%s.hdf5' % path
