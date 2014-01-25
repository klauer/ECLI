# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_pymca` -- ECLI pymca
===============================

.. module:: ecli_pymca
   :synopsis: Monkey-patch and load `pymca`_, an open-source
        x-ray fluorescence toolkit
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

.. _pymca: http://pymca.sourceforge.net
"""
from __future__ import print_function
import os
import sys
import time
import logging
import multiprocessing as mp
import xmlrpclib
import threading
import subprocess

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import get_plugin
from ecli_util.decorators import ECLIExport

# PyMca
import PyMca
import PyMca.spswrap as sps
from PyMca.PyMcaQt import QTimer
import PyMca.PyMcaMain

# others
import epics
import numpy as np

logger = logging.getLogger('ECLI.pymca')
MODULE_PATH = os.path.join(util.ECLI_PATH, __file__)

# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIpymca, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIpymca)


class ECLIpymca(ECLIPlugin):
    """
    Basic plotting support of scans via PyMca
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1),
                ('ECLIxmlrpc', 1)
                ]

    _callbacks = []

    use_subprocess = traitlets.Bool(True, config=True)

    def __init__(self, shell, config):
        super(ECLIpymca, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIpymca')
        self.pymca_process = None

    @property
    def logger(self):
        return logger

    def get_save_files(self):
        files = []
        base = 'ECLIScanWriter'
        plugins = ('HDF5', 'SPEC')
        for plugin_name in plugins:
            plugin_name = '%s%s' % (base, plugin_name)
            try:
                plugin = get_plugin(plugin_name)
            except:
                pass
            else:
                files.append(plugin.filename)

        return files

    @property
    def xmlrpc_url(self):
        return get_plugin('ECLIxmlrpc').server_url

    @ECLIExport
    def pymca(self, *other_args):
        """
        Start PyMca
        """

        args = [self.xmlrpc_url] + self.get_save_files()

        try:
            if self.use_subprocess:
                args = [sys.executable, MODULE_PATH] + args
                self.pymca_process = subprocess.Popen(args)
            else:
                #context = epics.ca.current_context()
                #epics.ca.detach_context()
                self.pymca_process = mp.Process(target=start_pymca,
                                                args=args,
                                                )
                self.pymca_process.start()

        except Exception as ex:
            print("Failed to spawn pymca process (%s) %s" %
                  (ex.__class__.__name__, ex))
            self.pymca_process = None
        #finally:
        #    if not self.use_subprocess:
        #        epics.ca.attach_context(context)

    def exit(self):
        if self.pymca_process is not None:
            print('Waiting for PyMca to close...')
            if hasattr(self.pymca_process, 'join'):
                self.pymca_process.join()
            #else:
            #    self.pymca_process.wait()


EPICS_TAG = 'EPICS'

# http://www.esrf.eu/blissdb/macros/macdoc.py?macname=xia2x.mac :
# XIA_DATA = spectrum for all detectors
# XIA_STAT = run statistics for all detectors (nevt, icr, ocr, lvt)
# XIA_SUMDATA = sum of spectrums if defined

SCAN_TAG = 'SCAN'
SCAN_ENV_TAG = '%s_ENV' % (SCAN_TAG, )


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
            #print('category', category, 'array', arr)
            for i, pv in enumerate(pvs_):
                if not pv:
                    continue

                cb = lambda arr=arr, i=i, **kwargs: update_array(arr, i, **kwargs)
                value = epics.caget(pv)
                #print('Monitoring "%s" = %s (%s[%d])' % (pv, value, category, i))
                epics.camonitor(pv, callback=cb)
                cb(pvname=pv, value=value)

        # TODO assumes all spectra are same length
        # sometimes type(self.spectrum[1]) == int? TODO: bug

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


class EpicsBridge(object):
    instance = None
    init_thread = None

    def __init__(self, url):
        self.cache = {}

        print('Epics Bridge', url)
        self._scan_info = {}
        self._scan_data = {}
        self._last_data = []

        self._url = None
        # Setting the url property, causes the xmlrpc serverproxy to connect
        self.url = url
        self.detectors = {}
        self.array_list = [SCAN_TAG]
        self.scan_arrays = {}

        for detector, pv_info in self.server.get_detector_list():
            self.monitor_detector(detector, pv_info)

        self._update_available = True
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
        print('Monitor detector %s (pvs: %s)' % (name, pvs))
        self.detectors[name] = det = EpicsDetector(name, pvs)
        self.array_list.append(name)
        if hasattr(det, 'calibration'):
            self.array_list.append('%s_PARAM' % name)

    def remove_detector(self, name):
        if name not in self.detectors:
            return

        del self.detectors[name]

    def update(self):
        if self.server is None:
            return

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
        return self.scan_info.get('nopts', 0), self.scan_info.get('counters', 0)

    def _update_scan_info(self):
        if self.server is None or not self.update_available:
            return

        self._scan_info = info = self.server.get_scan_info()
        if 'key' not in info:
            print('scan info has no key?', info)
            return

        self._scan_key = info['key']

        ndim = info.get('ndim', 1)
        labels = info.get('labels', [])
        label_str = ','.join(labels)
        # todo
        label_str = label_str.replace('(', '')
        label_str = label_str.replace(')', '')

        info['plotlist'] = label_str
        info['axistitles'] = label_str.replace(',', ' ')

        if ndim == 2:
            old_keys = set(self.scan_arrays.keys())
            keys = set(['2D_%s' % label for label in labels])
            if keys != old_keys:
                remove_keys = old_keys - keys
                for remove in remove_keys:
                    del self.scan_arrays[remove]
                for key in keys:
                    if key not in self.scan_arrays:
                        self.scan_arrays[key] = {'key': -1}
        else:
            self.scan_arrays.clear()

        print('got scan info', info)
        self._last_data.append(self._scan_data)
        self._scan_data = np.array(self.server.get_scan_data())
        self._update_available = False
        return info

    def getarrayinfo(self, name):
        # rows, cols, type, flag
        print('get array info', name)
        if name.startswith(SCAN_TAG):
            self._update_scan_info()
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
            dim = self.scan_info.get('dimensions')
            print('array info', name, dim)
            return [dim[0], dim[1], sps.FLOAT, sps.TAG_ARRAY | sps.TAG_IMAGE]

    def getarraylist(self):
        return self.array_list + list(self.scan_arrays.keys())

    def _isupdated(self, name):
        if self.server is None:
            return False

        if name in self.detectors:
            if self.detectors[name].updated:
                self.detectors[name].updated = False
                return True

        elif name == SCAN_TAG:
            return self.update_available

        elif name in self.scan_arrays:
            last_key = self.scan_arrays[name]['key']
            return (self.update_available or last_key != self._scan_key)

        return False

    def isupdated(self, name):
        ret = self._isupdated(name)
        print('isupdated %s = %s' % (name, ret))
        return ret

    def getenv(self, shmenv, key):
        print('getenv', shmenv, key)
        if shmenv == SCAN_ENV_TAG:
            return self.scan_info[key]
        else:
            return ''

    @property
    def update_available(self):
        if not self._update_available:
            newest_key = self.server.get_scan_key()
            self._update_available = (newest_key != self._scan_key)
            return self._update_available
        else:
            return True

    @property
    def scan_info(self):
        if self._scan_info is None or self.update_available:
            self._update_scan_info()
        return self._scan_info

    @property
    def scan_data(self):
        if self._scan_data is None or self.update_available:
            self._update_scan_info()
        return self._scan_data

    def _getdata(self, name):
        print('getdata', name)
        if name == SCAN_TAG:
            return self.scan_data
        elif name.endswith('_PARAM'):  # calibration
            detector = name.rsplit('_', 1)[0]
            return np.array([self.detectors[detector].calibration])
        elif name in self.detectors:
            return self.detectors[name].data.T  # expects transpose
        elif name in self.scan_arrays:
            self.scan_arrays[name]['key'] = self._scan_key

            # Strip off the 2D_ prefix
            name = name[3:]
            labels = self.scan_info['labels']
            label_idx = labels.index(name)

            data = self.scan_data
            data = data[:, label_idx]

            if 0:
                data = data + np.random.random(data.shape[0])
            import traceback
            traceback.print_stack()
            return np.array(data).reshape(self.scan_info['dimensions'])
        else:
            return np.zeros(1)

    def getdata(self, name):
        ret = self._getdata(name)
        #print('getdata %s = %s' % (name, ret))
        return ret

    def getkeylist(self, shmenv):
        if shmenv == SCAN_ENV_TAG:
            return self.scan_info.keys()
        else:
            return []

    def specrunning(self):
        return 1

    def getspeclist(self):
        #import traceback; traceback.print_stack()
        return [EPICS_TAG] + sps._getspeclist()

    # unused functions:
    def updatedone(self, shmenv):
        raise NotImplementedError
        # unused in current PyMca code

    def getdatacol(self, shm, idx):
        raise NotImplementedError
        # unused in current PyMca code

    def getdatarow(self, shm, idx):
        raise NotImplementedError
        # unused in current PyMca code

    def putenv(self, shmenv, cmd, outp):
        raise NotImplementedError
        # unused in current PyMca code


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
    epics.ca.use_initial_context()

    while EpicsBridge.instance is None:
        try:
            EpicsBridge.instance = eb = EpicsBridge(xmlrpc_url)
        except Exception as ex:
            print('Unable to connect to EPICS bridge: (%s) %s' %
                  (ex.__class__.__name__, ex, ), file=sys.stderr)
            raise
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


def pymca_print(s, end=''):
    if 1:
        with open('pymca_log.txt', 'at') as f:
            print(s, end=end, file=f)
    else:
        print(s, end=end, file=sys.__stdout__)


def start_pymca(xmlrpc_url, *files):
    """
    .. note:: this runs in a separate process from ECLI
    """

    if 0:  # epics.__version__ <= '3.2.3':
        # This still doesn't work with multiprocessing --
        # bug filed with pyepics: https://github.com/pyepics/pyepics/issues/15
        epics._CACHE_.clear()
        epics._MONITORS_.clear()
        epics.ca._cache.clear()
        epics.ca._put_done.clear()
        epics.ca.libca = None
        epics.ca.initial_context = None

    from ecli_util.misc import OutputStreamHandler
    sys.stdout = OutputStreamHandler(pymca_print)
    sys.stderr = OutputStreamHandler(pymca_print)

    wrap_pymca(xmlrpc_url)

    from PyMca import PyMcaQt as qt
    app = qt.QApplication.instance()
    if app is None:
        app = qt.QApplication([])

    main = PyMca.PyMcaMain.PyMcaMain()
    main.show()

    try:
        source_sel = main.sourceWidget.sourceSelector
        for fn in files:
            source_sel.openFile(fn)

        source_sel.openFile(EPICS_TAG, specsession=True)
    except:
        pass

    app.exec_()

if __name__ == '__main__':
    start_pymca(*sys.argv[1:])
