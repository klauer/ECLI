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
from ecli_util import get_plugin

from pyspecfile import SPECFileWriter

logger = logging.getLogger('ECLI.ScanWriterSPEC')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScanWriterSPEC, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScanWriterSPEC)


class ECLIScanWriterSPEC(ECLIPlugin):
    """
    ECLI SPEC file writer for scans
    """
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
        self._motors = []

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
        """
        Callback: called before a scan starts
        """
        extra_pv_info = scan.read_extra_pvs()
        self._motors = [pvname for desc, pvname, value in extra_pv_info]

        if self._file is None:
            if not self.filename:
                logger.error('SPEC file not set; scan will not be saved. (See: `%%scan_save` or %%config %s)' %
                             self.__class__.__name__)
                return

            elif not self._open_output():
                return

        self._new_scan = True
        self._scan_number = scan_number
        self._file._comment = scan.comments

        self._file._motors = self._motors
        self._file.write_scan_start(number=scan_number, command=command,
                                    seconds=scan.dwelltime)
        self._file.write_motor_positions((value for desc, pvname, value
                                          in extra_pv_info))

    def post_scan(self, scan=None, abort=False, **kwargs):
        """
        Callback: called after a scan finishes
        """
        if self._file is None:
            return

        self._file.finish_scan()

    def single_step(self, scan=None, grid_point=(), point=0, array_idx=0,
                    timestamps=None, **kwargs):
        """
        Callback: called after every single point in a stepscan
        """
        if self._file is None:
            return

        data = [(c, c.buff[array_idx]) for c in scan.counters]
        scalar_info = [(counter.label, d) for counter, d in data
                       if not isinstance(d, np.ndarray)]

        if timestamps is not None:
            # Make timestamps relative to the starting time of the file
            t0 = self._file.start_time
            t1 = timestamps[array_idx]
            scalar_info.insert(0, ('Epoch', t1 - t0))

        scalar_data = [d for counter, d in scalar_info]
        array_data = [d for counter, d in data
                      if isinstance(d, np.ndarray)]

        if self._new_scan:
            labels = [util.fix_label(label) for label, d in scalar_info]

            self._file.write_scan_data_start(labels)
            self._new_scan = False

        self._file.write_scan_data(scalar_data)
        self._file.write_mca_data(array_data)

    def _open_output(self):
        try:
            self._file = SPECFileWriter(self.filename, motors=self._motors)
        except Exception as ex:
            logger.error('Unable to use SPEC file "%s": (%s) %s' %
                         (self.filename, ex.__class__.__name__, ex))
            self._file = None
            return False
        else:
            self.scan_plugin.set_min_scan_number(self._file.scan_number)
            logger.debug('Last scan number %d' % self._file.scan_number)
            return True

    def _filename_changed(self, name=None, old=None, new=None):
        self._open_output()
        return True

    def save_path_set(self, path=None):
        """
        Callback: global save file path has changed
        """
        self.filename = u'%s.spec' % path
