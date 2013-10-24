# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_scanwriter_spec` -- SPEC-format scan writer
======================================================

.. module:: ecli_scanwriter_spec
    :synopsis: ECLI SPEC format file writer for scans (:mod:`ecli_stepscan`)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""


from __future__ import print_function
import logging
import numpy as np

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import (get_plugin, get_core_plugin)

from pyspecfile import SPECFileWriter

logger = logging.getLogger('ECLI.ScanWriterSPEC')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScanWriterSPEC, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScanWriterSPEC)


class ECLIScanWriterSPEC(ECLIPlugin):
    VERSION = 1
    SCAN_PLUGIN = 'ECLIScans'
    REQUIRES = [('ECLICore', 1), (SCAN_PLUGIN, 1)]

    filename = traitlets.Unicode(u'', config=True)
    _callbacks = []

    def __init__(self, shell, config):
        logger.info('Initializing ECLI SPEC file writer plugin')
        self._scan_number = 0
        self._new_scan = True
        scan_plugin = get_plugin(self.SCAN_PLUGIN)
        self.scan_plugin = scan_plugin

        super(ECLIScanWriterSPEC, self).__init__(shell=shell, config=config)

        if self.filename:
            self._file = SPECFileWriter(self.filename)
        else:
            self._file = None

        callbacks = [(scan_plugin.CB_PRE_SCAN, self.pre_scan),
                     (scan_plugin.CB_POST_SCAN, self.post_scan),
                     (scan_plugin.CB_SCAN_STEP, self.single_step),
                     (scan_plugin.CB_SAVE_PATH, self.save_path_set),
                     ]

        for cb_name, fcn in callbacks:
            scan_plugin.add_callback(cb_name, fcn)

    @property
    def logger(self):
        return logger

    def pre_scan(self, scan=None, scan_number=0, command='', **kwargs):
        if self._file is None:
            logger.error('SPEC file not set; scan will not be saved. (See: %%config %s)' %
                         self.__class__.__name__)
            return

        self._new_scan = True
        self._scan_number = scan_number
        self._file._comment = scan.comments
        extra_pv_info = scan.read_extra_pvs()

        self._file._motors = [pvname for desc, pvname, value in extra_pv_info]
        self._file.write_scan_start(number=scan_number, command=command,
                                    seconds=scan.dwelltime)
        self._file.write_motor_positions((value for desc, pvname, value
                                          in extra_pv_info))

    def post_scan(self, scan=None, abort=False, **kwargs):
        if self._file is None:
            return

        pass

    def single_step(self, scan=None, grid_point=(), point=0, array_idx=0,
                    **kwargs):
        if self._file is None:
            return

        data = [(c, c.buff[array_idx]) for c in scan.counters]
        scaler_data = [d for counter, d in data
                       if not isinstance(d, np.ndarray)]
        array_data = [d for counter, d in data
                      if isinstance(d, np.ndarray)]

        if self._new_scan:
            self._file.write_scan_data_start([util.fix_label(c.label) for c, d in data
                                              if not isinstance(d, np.ndarray)])
            self._new_scan = False

        self._file.write_scan_data(scaler_data)
        self._file.write_mca_data(array_data)

    def _filename_changed(self, name=None, old=None, new=None):
        try:
            self._file = SPECFileWriter(self.filename)
        except Exception as ex:
            logger.error('Unable to use SPEC file "%s": (%s) %s' %
                         (self.filename, ex.__class__.__name__, ex))
            return False
        else:
            self.scan_plugin.set_min_scan_number(self._file.scan_number)
            return True

    def save_path_set(self, path=None):
        self.filename = u'%s.spec' % path
