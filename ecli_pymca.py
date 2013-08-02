# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_pymca` -- ECLI pymca
===============================

.. module:: ecli_pymca
   :synopsis: Monkey-patch and load pymca
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""
from __future__ import print_function
import os
import sys
import time
import logging
import multiprocessing as mp
import xmlrpclib
import threading

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (
    argument, magic_arguments, parse_argstring)

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util.decorators import ECLIExport

# PyMca
import PyMca
import PyMca.spswrap as sps
from PyMca.PyMcaQt import QTimer
import PyMca.PyMcaMain

# others
import epics
import numpy as np

logger = logging.getLogger('ECLIpymca')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIpymca, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIpymca)


class ECLIpymca(ECLIPlugin):
    """
    DESCRIPTION
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1), ('ECLIxmlrpc', 1)]
    EXPORTS = {}  # see __init__

    _callbacks = []

    def __init__(self, shell, config):
        super(ECLIpymca, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIpymca')
        self.pymca_process = None

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIpymca')

    @property
    def logger(self):
        return logger

    @ECLIExport
    def pymca(self):
        """
        Start PyMca
        """

        xmlrpc_plugin = get_plugin('ECLIxmlrpc')
        url = xmlrpc_plugin.server_url

        self.pymca_process = mp.Process(target=start_pymca, args=(url, ))
        self.pymca_process.start()

    def exit(self):
        if self.pymca_process is not None:
            print('Waiting for PyMca to close...')  # <-- TODO
            self.pymca_process.join()


EPICS_TAG = 'EPICS'

# http://www.esrf.eu/blissdb/macros/macdoc.py?macname=xia2x.mac :
# XIA_DATA = spectrum for all detectors
# XIA_STAT = run statistics for all detectors (nevt, icr, ocr, lvt)
# XIA_SUMDATA = sum of spectrums if defined

SCAN_TAG = 'SCAN'
SCAN_ENV_TAG = '%s_ENV' % (SCAN_TAG, )

# TODO run updates in a separate thread
class EpicsDetector(object):
    def __init__(self, name, pvs):
        print('--Detector %s--' % name)

        def update_array(arr, i, value=None, pvname=None, **kwargs):
            print('%s[%d]=%s (%s updated)' % (pvname, i, value, name))
            arr[i] = value
            self.updated = True

        self.name = name
        # All of the PVs:
        self.pvs = sum((list_ for list_ in pvs.values()), [])
        for category, pvs_ in pvs.iteritems():
            arr = [0] * len(pvs_)
            setattr(self, category, arr)
            for i, pv in enumerate(pvs_):
                if not pv:
                    continue

                cb = lambda arr=arr, i=i, **kwargs: update_array(arr, i, **kwargs)
                print('Monitoring "%s"' % pv)
                epics.camonitor(pv, callback=cb)
                cb(pvname=pv, value=epics.caget(pv))
                print('Monitored "%s"' % pv)

        # TODO assumes all spectra are same length
        self.spectrum[0] = np.arange(len(self.spectrum[1]))

    @property
    def sps_info(self):
        return [self.channels[0], 1, sps.FLOAT, sps.TAG_MCA | sps.TAG_ARRAY]

    @property
    def data(self):
        return np.array(self.spectrum)

    def clear(self):
        for pv in self.pvs:
            epics.camonitor_clear(pv)

#pymca_env = {'datafile': '/dev/null',
#            'plotlist': 'list,of,plots,4,5',
#            'title': 'title',
#            'nopts': 5,
#            #'axistitles': '1 2 3 4 5',
#            'axistitles': 'a{1} b{2} c{3} d{4} e{5}',
#            'H': 1.0,
#            'K': 2.0,
#            'L': 3.0,
#            'xlabel': 'x label',
#            'ylabel': 'y label',
#            }


class EpicsBridge(object):
    instance = None
    init_thread = None

    # TODO pass the URL in with mp
    def __init__(self, url):  #url='http://localhost:8988/epics_sps'):
        self.cache = {}

        print('Epics Bridge', url)
        self._url = None
        self.url = url
        self.detectors = {}
        self.array_list = [SCAN_TAG]
        self.scan_arrays = []

        for detector, pv_info in self.server.get_detector_list():
            self.monitor_detector(detector, pv_info)

        self.scan_info = {}
        self.update_timer = QTimer()
        self.update_timer.start(500)
        self.update_timer.timeout.connect(self.update)

    def _get_url(self):
        return self._url
    def _set_url(self, url):
        if url != self._url:
            self.server = xmlrpclib.ServerProxy(url)
            self._url = url

    url = property(_get_url, _set_url, doc='XMLRPC server URL')

    def monitor_detector(self, name, pvs):
        print('monitor detector', name, pvs)
        self.detectors[name] = det = EpicsDetector(name, pvs)
        self.array_list.append(name)
        if hasattr(det, 'calibration'):
            self.array_list.append('%s_PARAM' % name)

    def remove_detector(self, name):
        if name not in self.detectors:
            return

        del self.detectors[name]

    def update(self):
        # check to add/remove detectors
        det_list = self.server.get_detector_list()
        det_dict = dict(det_list)
        det_names = set(det_dict.keys())

        new_detectors = det_names - set(self.detectors.keys())
        for det_name in new_detectors:
            self.monitor_detector(det_name, det_dict[det_name])

        remove_detectors = set(self.detectors.keys()) - det_names
        for det_name in remove_detectors:
            self.remove_detector(det_name)

        # see if scan in progress, and get status

    @property
    def scan_dim(self):
        return self.scan_info.get('nopts', 0), self.scan_info.get('_counters', 0)

    def _update_scan_info(self):
        self.scan_info = info = self.server.get_scan_info()

        ndim = info.get('_ndim', 1)
        labels = info.get('_labels', [])
        label_str = ','.join(labels)
        # todo
        label_str = label_str.replace('(', '')
        label_str = label_str.replace(')', '')

        info['plotlist'] = label_str
        info['axistitles'] = label_str.replace(',', ' ')

        del self.scan_arrays[:]
        if ndim == 2:
            for label in labels:
                self.scan_arrays.append('2D_%s' % label)

        print('got scan info', info)
        return info

    def getarrayinfo(self, name):
        # rows, cols, type, flag
        print('get array info', name)
        if name.startswith(SCAN_TAG):
            info = self._update_scan_info()
            nopts, counters = self.scan_dim
            print('Scan points', nopts, 'Counters', counters)
            return [nopts, counters, sps.FLOAT, sps.TAG_SCAN | sps.TAG_ARRAY]
        elif name in self.detectors:
            det = self.detectors[name]
            return det.sps_info
        elif name.endswith('_PARAM'):  # calibration
            #detector = name.rsplit('_', 1)[0]
            return [3, 1, sps.FLOAT, sps.TAG_ARRAY]
        elif name in self.scan_arrays:
            name = name[3:]
            dim = self.scan_info.get('_dimensions')
            print('array info', name, dim)
            return [dim[0], dim[1], sps.FLOAT, sps.TAG_ARRAY | sps.TAG_IMAGE]
        else:
            print('unhandled array', name, self.scan_arrays)

    def getarraylist(self):
        print('* array list is', self.array_list + self.scan_arrays)
        return self.array_list + self.scan_arrays

    def isupdated(self, name):
        if name in self.detectors:
            if self.detectors[name].updated:
                self.detectors[name].updated = False
                return True
        elif name == SCAN_TAG:
            key = self.server.get_scan_key()
            print('server key', key, 'local key', self.scan_key)
            return (key != self.scan_key)

        return False

    @property
    def scan_key(self):
        return self.scan_info.get('scan_key', -1)

    def getenv(self, shmenv, key):
        print('getenv', shmenv, key)
        if shmenv == SCAN_ENV_TAG:
            return self.scan_info[key]
        else:
            return ''

    def getdata(self, name):
        print('getdata', name)
        if name == SCAN_TAG:
            return np.array(self.server.get_scan_data())
        elif name.endswith('_PARAM'):  # calibration
            detector = name.rsplit('_', 1)[0]
            return np.array([self.detectors[detector].calibration])
        elif name in self.detectors:
            return self.detectors[name].data.T  # expects transpose
        elif name in self.scan_arrays:
            name = name[3:]
            labels = self.scan_info['_labels']
            label_idx = labels.index(name)

            data = np.array(self.server.get_scan_data())
            data = data[:, label_idx]
            print('data is', data, 'shape', np.shape(data))
            print('dimensions', self.scan_info['_dimensions'])
            return np.array(data).reshape(self.scan_info['_dimensions'])
        else:
            print('hmm? name=%s' % name)  # TODO
            return [0]

    def getkeylist(self, shmenv):
        #print('shmenv is', shmenv)
        if shmenv == SCAN_ENV_TAG:
            return self.scan_info.keys()
        else:
            return []

    def specrunning(self):
        return 1

    def getspeclist(self):
        # TODO:
        # Initializing the monitors prior to PyMca startup results in similar behavior
        # as seen on the command line -- 4 second timeouts on arrays. Likely pyepics bug,
        # but can't easily reproduce...
        return [EPICS_TAG] + sps._getspeclist()

    # unused functions:
    def updatedone(self, shmenv):
        print('updatedone', shmenv)
        return 0

    def getdatacol(self, shm,idx):
        print('** unused? getdatacol idx', shm, idx)
        return []

    def getdatarow(self, shm,idx):
        print('** unused? getdatarow idx', shm, idx)
        return []

    def putenv(self, shmenv,cmd,outp):
        # unused in PyMca
        print('epics putenv', shmenv, cmd, outp)
        return 1


def wrap_sps(sps_fcn, epics_fcn):
    """
    (decorator)
    Allow for the SPEC functionality to still work by wrapping
    the old SPS functions, only filtering out ones that match EPICS_TAG
    """
    def wrapped(spec, *args):
        if spec == EPICS_TAG:
            return epics_fcn(*args)
        else:
            return sps_fcn(spec, *args)
    return wrapped


def init_epicsbridge(xmlrpc_url):
    # TODO wrap this all up in the EpicsBridge class -- this isn't how it should be done
    while EpicsBridge.instance is None:
        try:
            EpicsBridge.instance = eb = EpicsBridge(xmlrpc_url)
        except Exception as ex:
            print('Unable to connect to EPICS bridge: (%s) %s' %
                  (ex.__class__.__name__, ex, ), file=sys.stderr)
            time.sleep(5)
        else:
            for fcn in ('getarrayinfo', 'getarraylist', 'isupdated',
                        'getenv', 'getdata', 'getkeylist', 'specrunning',
                        'updatedone', 'getdatacol', 'getdatarow', 'putenv',
                        ):

                orig_fcn = getattr(sps, fcn)
                epics_fcn = getattr(eb, fcn)
                wrapped_fcn = wrap_sps(orig_fcn, epics_fcn)
                setattr(sps, fcn, wrapped_fcn)
                setattr(sps, '_%s' % fcn, orig_fcn)

            sps._getspeclist = sps.getspeclist
            sps.getspeclist = eb.getspeclist


def wrap_pymca(xmlrpc_url):
    if EpicsBridge.instance is None:
        if EpicsBridge.init_thread is None:
            logger.debug('PyMca/epics bridge init thread')
            EpicsBridge.init_thread = threading.Thread(target=init_epicsbridge,
                                                       args=(xmlrpc_url, ))
            EpicsBridge.init_thread.run()
    else:
        inst = EpicsBridge.instance
        inst.url = xmlrpc_url

def pymca_print(s):
    #print('(pymca) %s' % s, file=sys.__stdout__)
    pass

def start_pymca(xmlrpc_url):
    """
    .. note:: this runs in a separate process from ECLI
    """

    wrap_pymca(xmlrpc_url)

    from ecli_util.misc import OutputStreamHandler
    sys.stdout = OutputStreamHandler(pymca_print)
    sys.stderr = OutputStreamHandler(pymca_print)

    # TODO check instance
    from PyMca import PyMcaQt as qt
    app = qt.QApplication.instance()
    if app is None:
        app = qt.QApplication([])

    main = PyMca.PyMcaMain.PyMcaMain()
    main.show()
    app.exec_()

