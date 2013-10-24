# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_scanwriter_hdf5` -- HDF5 scan writer
===============================================

.. module:: ecli_scanwriter_hdf5
    :synopsis: ECLI HDF5 file writer for scans (:mod:`ecli_stepscan`)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
.. note:: requires h5py <http://www.h5py.org>
"""

from __future__ import print_function
import os
import logging
import numpy as np

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.error import UsageError

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import (get_plugin, get_core_plugin)

import h5py

logger = logging.getLogger('ECLI.ScanWriterHDF5')
SCAN_PLUGIN = 'Scans'


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScanWriterHDF5, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScanWriterHDF5)


class ECLIScanWriterHDF5(ECLIPlugin):
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
                     (scan_plugin.CB_SCAN_STEP, self.single_step)]

        self.scan_plugin = scan_plugin

        for cb_name, fcn in callbacks:
            scan_plugin.add_callback(cb_name, fcn)

    @property
    def logger(self):
        return logger

    def _new_scan(self, scan_number, overwrite=True):
        group_name = 'Scan_%.4d' % (scan_number, )
        logger.debug('New group name', group_name)
        try:
            group = self._scans_group.create_group(group_name)
        except ValueError:
            if overwrite:
                group = self._scans_group[group_name]
                logger.debug('Existing group', group)
                return group
            else:
                return None

        logger.debug('Created group', group)
        return group

    def _open_file(self, filename):
        if not filename:
            self._file = None
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
            self.filename = None
            self._file = None
            self._scan_group = None
            self._scans_group = None
            return False
        else:
            self.filename = filename
            self._scans_group = self._file.require_group('Scans')
            if not new_file:
                # TODO find the last scan number **
                self.scan_plugin.set_min_scan_number(0)

            return True

    def pre_scan(self, scan=None, scan_number=0, command='', dimensions=(), **kwargs):
        if self._file is None:
            logger.error('HDF5 file not set; scan will not be saved. (See: %%config %s)' %
                         self.__class__.__name__)
            return

        self._scan_number = scan_number
        self._file._comment = scan.comments
        extra_pv_info = scan.read_extra_pvs()

        self._scan_group = sgroup = self._new_scan(scan_number)
        # Attributes under the scan group:
        sgroup.attrs['number'] = scan_number
        sgroup.attrs['command'] = command
        sgroup.attrs['dwell_time'] = scan.dwelltime
        sgroup.attrs['start_timestamp'] = util.get_timestamp()
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
        if self._scan_group is None:
            return

        scan = self._scan_group
        scan.attrs['end_timestamp'] = util.get_timestamp()
        scan.attrs['elapsed'] = scan.attrs[
            'end_timestamp'] - scan.attrs['start_timestamp']

    def single_step(self, scan=None, grid_point=(), point=0, array_idx=0,
                    **kwargs):
        if self._file is None or self._scan_group is None:
            return

        scan_group = self._scan_group
        dimensions = scan_group.attrs['dimensions']

        # Create the data group if necessary
        data_group = scan_group.require_group('Data')
        for counter in scan.counters:
            data = counter.buff[array_idx]
            label = util.fix_label(counter.label)

            # Create the array in the data group if it doesn't already exist
            if label not in data_group:
                shape = dimensions + list(np.shape(data))
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
                dataset[array_idx] = data
            except IOError as ex:
                # TODO flag writing error and notify user somehow
                logger.error(u'%s (%s) %s' % (self.__class__.__name__,
                                              ex.__class__.__name__, ex))
                dataset[array_idx] = 0

        # TODO link to external files for additional detectors

    def _filename_changed(self, name, old, new):
        self._open_file(new)
