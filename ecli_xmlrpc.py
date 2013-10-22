# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_xmlrpc` -- ECLI XML RPC (remote procedure call) server
=================================================================

.. module:: ecli_xmlrpc
   :synopsis: Provides a simple interface to other programs via XML RPC,
       allowing sharing of data, a way to execute commands, and so on.
       Although there are plans to change it (TODO), it currently
       allows for scan visualization in PyMca
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

# TODO allow marshalling of numpy arrays
from __future__ import print_function
import logging
import threading
import numpy as np

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (argument,
                                          magic_arguments, parse_argstring)

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import (get_plugin, get_core_plugin)

# XMLRPC -- TODO replace with a library that does faster serialization/etc
#           this is only for a proof of concept
from SimpleXMLRPCServer import SimpleXMLRPCServer
from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler

logger = logging.getLogger('ECLI.xmlrpc')

# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIxmlrpc, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIxmlrpc)


def get_request_handler(path):
    class RequestHandler(SimpleXMLRPCRequestHandler):
        rpc_paths = (path, )

    return RequestHandler


class EpicsMCA(object):
    # TODO -- fix this up to be more useful

    """
    Epics MCA PV information for PyMca
    """
    _pvs = {'calibration': ['%s.CALO', '%s.CALS', '%s.CALQ'],
            'time': ['%s.ERTM', '%s.ELTM'],
            'channels': ['%s.NUSE'],
            'spectrum': ['', '%s.VAL'],
            }

    def __init__(self, name, prefix):
        self.pvs = {}
        self.name = name
        for pv_category, macro_list in self._pvs.iteritems():
            self.pvs[pv_category] = [macro % prefix if macro else ''
                                     for macro in macro_list]


class ECLIxmlrpc(ECLIPlugin):
    """
    ECLI xmlrpc server

    Functions prefixed with `server_` are automatically added to the
    list of remote procedure calls.
    """
    VERSION = 1
    SCAN_PLUGIN = 'ECLIScans'
    REQUIRES = [('ECLICore', 1), (SCAN_PLUGIN, 1)]

    _callbacks = []
    rpc_path = traitlets.Unicode(u'/epics_sps', config=True)
    port = traitlets.Int(8988, config=True)

    def __init__(self, shell, config):
        super(ECLIxmlrpc, self).__init__(shell=shell, config=config,
                                         init_traits=False)

        logging.info('Initializing ECLI xmlrpc server plugin')
        self._scan_number = 0

        scan_plugin = get_plugin(self.SCAN_PLUGIN)
        callbacks = [(scan_plugin.CB_PRE_SCAN,  self.pre_scan),
                     (scan_plugin.CB_POST_SCAN, self.post_scan),
                     (scan_plugin.CB_SCAN_STEP, self.single_step)]

        for cb_name, fcn in callbacks:
            self.core.add_callback(cb_name, fcn, extension=scan_plugin)

        self.server_functions = self._find_functions(prefix='server_')
        self.server_thread = None
        self.server = None
        self.handler = None
        self._scan_info = {}
        self._scan_data = {}
        self._new_scan = {}
        self._scan_key = 0

        self._reset()
        self._port_changed()

    @property
    def logger(self):
        return logger

    def _reset(self):
        self.detectors = [EpicsMCA('DXP', 'MLL:DXP:mca1'), ]
        #self.detectors = []

    def _find_functions(self, prefix=''):
        matches = [attr for attr in dir(self)
                   if attr.startswith(prefix)]
        functions = []
        for attr in matches:
            try:
                value = getattr(self, attr)
            except:
                continue
            else:
                if hasattr(value, '__call__'):
                    fixed_name = attr[len(prefix):]
                    functions.append((fixed_name, value))
                    logger.debug('Server fcn: %s %s' % (fixed_name, value))

        return functions

    def _port_changed(self, name='', old=None, new=None):
        port = self.port
        if self.server is not None:
            old_port = self.server.server_address[1]
            if old_port == port:
                return

        self.stop_server()
        self.start_server()

    def _rpc_path_changed(self, name='', old=0, new=0):
        path = self.rpc_path
        if self.handler is not None:
            if path in self.handler.rpc_paths:
                return

        self.stop_server()
        self.start_server()

    def stop_server(self):
        if self.server_thread is None:
            return

        print('Stopping server...', end=' ')
        self.server.shutdown()
        self.server_thread.join()
        print('done.')
        self.server_thread = None

    def start_server(self):
        """
        Start the XMLRPC server on the user-configured port
        """
        port = self.port
        print('Starting XMLRPC server on port=%d...' % port, end=' ')

        req_handler = get_request_handler(self.rpc_path)
        self.server = SimpleXMLRPCServer(("", port),
                                         requestHandler=req_handler,
                                         logRequests=False,
                                         allow_none=True)

        self.handler = req_handler

        self.server.register_introspection_functions()
        for name, function in self.server_functions:
            self.server.register_function(function, name)

        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.start()
        print('done.')

    def server_get_detector_list(self):
        """
        XMLRPC server function: get detector list
        :return: a list of tuples in the format (detector, pv_info),
            where pv_info is a dictionary like {'spectrum': 'spectrum_pv.VAL'}
        """
        # TODO this all needs reworking, it was just a proof of concept
        return [(det.name, det.pvs) for det in self.detectors]

    def server_get_scan_key(self):
        """
        The scan key is an integer tag which allows pymca, as the
        xmlrpc client, to know if the scan has updated.  (this is
        to mimic how pymca's SPS works)
        :return: the current scan key
        """
        return self._scan_key

    def server_get_scan_info(self):
        """
        XMLRPC server function: get scan information
        :return: the scan information in a dictionary
        """
        return self._scan_info

    def server_get_scan_data(self):
        """
        XMLRPC server function: get scan data
        :return: the scan data, in list format
        """
        return self._scan_data.tolist()

    def server_get_user_variable(self, var):
        """
        XMLRPC server function: get a variable from the user's namespace
        :param var: the variable name
        :return: the variable's value
        """
        return self.shell.user_ns[var]

    def server_set_user_variable(self, var, value):
        """
        XMLRPC server function: set a variable in the user's namespace
        :param var: the variable name
        :param value: the value to set
        :return: the old value (or None)
        """
        ns = self.shell.user_ns

        try:
            old_value = ns[var]
        except:
            old_value = None

        ns[var] = value
        return old_value

    def server_get_variable_list(self):
        """
        XMLRPC server function: list of variables in the user's namespace
        """
        return self.shell.user_ns.keys()

    def pre_scan(self, scan=None, **kwargs):
        """Scan callback -- new scan started"""
        self._new_scan = kwargs
        logger.debug('pre scan', self._new_scan)

    def post_scan(self, scan=None, abort=False, **kwargs):
        """Scan callback -- scan finished"""
        pass

    def single_step(self, scan=None, point=0, array_idx=0, **kwargs):
        """Scan callback per point -- prepares data for pymca"""
        scan_info = self._scan_info

        self._scan_key = (self._scan_key + 1) % 10000
        scan_info['key'] = self._scan_key

        scaler_counters = [c for c in scan.counters
                           if not isinstance(c.buff[array_idx], np.ndarray)]
        array_counters = [c for c in scan.counters
                          if c not in scaler_counters]
        if self._new_scan is not None:
            logger.debug('--> new scan')
            num_points = 1
            for d in self._new_scan['dimensions']:
                num_points *= d  # operator.mul...

            scan_info['title'] = '#%d %s' % (self._new_scan['scan_number'],
                                             self._new_scan['command'])

            labels = [util.fix_label(c.label) for c in scaler_counters]
            logger.debug('labels', labels)
            scan_info['nopts'] = num_points
            scan_info['_labels'] = labels
            scan_info['_dimensions'] = self._new_scan['dimensions']
            scan_info['_ndim'] = self._new_scan['ndim']
            scan_info['_counters'] = len(labels)

            self._scan_data = np.zeros((num_points, len(labels)))
            self._new_scan = None

        logger.debug('scan info', scan_info)
        #data = [(c, c.buff[array_idx]) for c in scan.counters]
        scaler_data = [c.buff[array_idx] for c in scaler_counters]
        array_data = [c.buff[array_idx] for c in array_counters]
        for i, s_data in enumerate(scaler_data):
            self._scan_data[array_idx, i] = s_data

    def exit(self):
        ECLIPlugin.exit(self)

        self.stop_server()

    @property
    def server_url(self):
        return 'http://localhost:%d%s' % (self.port, self.rpc_path)
        # TODO
