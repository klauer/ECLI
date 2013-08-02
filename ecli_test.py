# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_test` -- ECLI extension testbed
==========================================

.. module:: ecli_test
   :synopsis: write functions here, move them to appropriate modules after
.. moduleauthor:: x <y@z>
"""
from __future__ import print_function
import os
import sys
import time
import logging

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (
    argument, magic_arguments, parse_argstring)
from IPython.core.error import UsageError

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util import ECLIError
from ecli_util.decorators import ECLIExport

logger = logging.getLogger('ECLITest')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLITest, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLITest)
# -


class ECLITest(ECLIPlugin):
    """
    DESCRIPTION
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}  # see __init__

    _callbacks = []
    param = traitlets.List(traitlets.Unicode,
                           default_value=('m1', 'm2'),
                           config=True)
    param2 = traitlets.Int(8, config=True)

    def __init__(self, shell, config):
        # ECLITest.EXPORTS = {}

        super(ECLITest, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLITest')

    @staticmethod
    def get_plugin():
        return get_plugin('ECLITest')

    def _param_changed(self, *args):
        pass

    @property
    def logger(self):
        return logger

    @ECLIExport
    def pymca(self):
        import multiprocessing as mp
        self.p = mp.Process(target=start_pymca, args=())
        self.p.start()

    def exit(self):
        print('exit')
        if hasattr(self, 'p'):
            self.p.join()




EPICS_TAG = 'EPICS'

# http://www.esrf.eu/blissdb/macros/macdoc.py?macname=xia2x.mac :
# XIA_DATA = spectrum for all detectors
# XIA_STAT = run statistics for all detectors (nevt, icr, ocr, lvt)
# XIA_SUMDATA = sum of spectrums if defined

import numpy as np
import PyMca.spswrap as spswrap
import xmlrpclib
from PyMcaQt import QTimer
import epics
import threading

def wrap(sps_fcn, epics_fcn):
    """
    Allow for the SPEC functionality to still work by wrapping
    the old SPS functions, only filtering out ones that match EPICS_TAG
    """
    def wrapped(spec, *args):
        if spec == EPICS_TAG:
            return epics_fcn(*args)
        else:
            return sps_fcn(spec, *args)
    return wrapped

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

test_env = {'datafile': '/dev/null',
            'plotlist': 'list,of,plots,4,5',
            'title': 'title',
            'nopts': 5,
            #'axistitles': '1 2 3 4 5',
            'axistitles': 'a{1} b{2} c{3} d{4} e{5}',
            'H': 1.0,
            'K': 2.0,
            'L': 3.0,
            'xlabel': 'x label',
            'ylabel': 'y label',
            }


class EpicsBridge(object):
    instance = None
    init_thread = None

    # TODO make the URL configurable somehow (modify command-line processing
    #   function?)
    def __init__(self, url='http://localhost:8988/epics_sps'):
        self.cache = {}

        print('Epics Bridge', url)
        self.server = xmlrpclib.ServerProxy(url)
        self.detectors = {}
        self.array_list = [SCAN_TAG]
        self.scan_arrays = []

        for detector, pv_info in self.server.get_detector_list():
            self.monitor_detector(detector, pv_info)

        self.scan_info = {}
        self.update_timer = QTimer()
        self.update_timer.start(500)
        self.update_timer.timeout.connect(self.update)

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

    # unused functions:
    #def updatedone(self, shmenv):
    #    print('updatedone', shmenv)
    #    return 0

    #def getdatacol(self, shm,idx):
    #    print('** unused? getdatacol idx', shm, idx)
    #    return []

    #def getdatarow(self, shm,idx):
    #    print('** unused? getdatarow idx', shm, idx)
    #    return []

    #def putenv(self, shmenv,cmd,outp):
    #    # unused in PyMca
    #    print('epics putenv', shmenv, cmd, outp)
    #    return 1


def init_epicsbridge():
    # TODO wrap this all up in the EpicsBridge class -- this isn't how it should be done
    while EpicsBridge.instance is None:
        try:
            EpicsBridge.instance = eb = EpicsBridge()
        except Exception as ex:
            print('Unable to connect to EPICS bridge: (%s) %s' %
                  (ex.__class__.__name__, ex, ), file=sys.stderr)
            time.sleep(5)
        else:
            globals()['getarrayinfo'] = wrap(spswrap.getarrayinfo, eb.getarrayinfo)
            globals()['getarraylist'] = wrap(spswrap.getarraylist, eb.getarraylist)
            globals()['isupdated'] = wrap(spswrap.isupdated, eb.isupdated)
            globals()['getenv'] = wrap(spswrap.getenv, eb.getenv)
            globals()['getdata'] = wrap(spswrap.getdata, eb.getdata)
            globals()['getkeylist'] = wrap(spswrap.getkeylist, eb.getkeylist)
            globals()['specrunning'] = wrap(spswrap.specrunning, eb.specrunning)
            #updatedone = wrap(spswrap.updatedone, eb.updatedone)
            #getdatacol = wrap(spswrap.getdatacol, eb.getdatacol)
            #getdatarow = wrap(spswrap.getdatarow, eb.getdatarow)
            #putenv = wrap(spswrap.putenv, eb.putenv)


def getspeclist():
    # TODO:
    # Initializing the monitors prior to PyMca startup results in similar behavior
    # as seen on the command line -- 4 second timeouts on arrays. Likely pyepics bug,
    # but can't easily reproduce...
    if EpicsBridge.instance is None:
        if EpicsBridge.init_thread is None:
            print('new init thread')
            EpicsBridge.init_thread = threading.Thread(target=init_epicsbridge)
            EpicsBridge.init_thread.run()

    return [EPICS_TAG] + spswrap.getspeclist()
def pymca_print(s):
    print('(pymca) %s' % s, file=sys.__stdout__)

def start_pymca(args):
    import os
    import sys
    sys.path.insert(0, '/home/nanopos/pymca-code-1909/virt_env/lib/python2.7/site-packages/')
    import PyMca
    import PyMca.PyMcaMain

    from ecli_util.misc import OutputStreamHandler
    sys.stdout = OutputStreamHandler(pymca_print)
    sys.stderr = OutputStreamHandler(pymca_print)

    # todo check instance
    from PyMca import PyMcaQt as qt
    app = qt.QApplication(sys.argv)

    sys.path.insert(0, os.path.dirname(PyMca.__file__))
    fname = os.path.join(os.path.dirname(PyMca.__file__), 'PyMcaMain.py')

    sys.argv = []
    m = PyMca.PyMcaMain.PyMcaMain()
    m.show()
    app.exec_()

