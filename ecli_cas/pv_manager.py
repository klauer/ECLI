# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_cas.pv_manager` -- ECLI CAS PV manager
=============================================

.. module:: ecli_cas
   :synopsis: ECLI channel access server process variable manager
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import logging

# pcaspy
import pcaspy
from pcaspy.tools import ServerThread

from . import CAPVBadValue

logger = logging.getLogger('ECLIcas')


class CAPV(pcaspy.SimplePV):
    """
    Simple wrapper around pcaspy.SimplePV to add write callback
    functionality, and a simple way to update the value directly
    from the PV instance (see write_value)
    """
    def __init__(self, prefix, basename, pvinfo, **kwargs):
        name = '%s%s' % (prefix, basename)
        self.prefix = prefix
        self.basename = basename

        super(CAPV, self).__init__(name, pvinfo, **kwargs)
        self._write_callbacks = set([])

    def add_write_callback(self, fcn):
        assert(hasattr(fcn, '__call__'))
        self._write_callbacks.add(fcn)

    def written_to(self, value):
        """
        Callback from CAS Driver -- runs all callbacks, accepting
        the new value only if CAPVBadValue is not raised during
        any of the callbacks
        """
        for cb in self._write_callbacks:
            try:
                cb(pv=self, pvname=self.name, value=value)
            except CAPVBadValue:
                return False
            except:
                pass

        return True

    def write_value(self, value):
        """
        Update the PV to have a new value
        """
        self.driver.setParam(self.basename, value)


class CAServer(pcaspy.SimpleServer):
    def __init__(self):
        pcaspy.SimpleServer.__init__(self)
        self.pcas_manager = pcaspy.driver.manager
        self.pvs = None

    def __del__(self):
        pcaspy.asCaStop()

    def pvExistTest(self, context, addr, fullname):
        """
        Callback from CAS -- checks to see if this server has the PV or not
        """
        if fullname in self.pcas_manager.pvf:
            return pcaspy.pverExistsHere
        else:
            return pcaspy.pverDoesNotExistHere

    def pvAttach(self, context, fullname):
        return self.pcas_manager.pvf.get(fullname, pcaspy.S_casApp_pvNotFound)

    def _create_pv(self, prefix, basename, pvinfo):
        """
        :param prefix: the pv prefix
        :type prefix: str
        :param basename: prefix+basename gives the full pv name
        :type basename: str
        :param pvinfo: contains PV information (see PCASpy docs)
        :type pvinfo: dict
        """
        logger.debug('create pv', basename, pvinfo)
        pvinfo = pcaspy.PVInfo(pvinfo)
        pvinfo.reason = basename
        pvinfo.name = '%s%s' % (prefix, basename)

        pv = CAPV(prefix, basename, pvinfo)
        if pvinfo.port not in self.pcas_manager.pvs:
            self.pcas_manager.pvs[pvinfo.port] = {}

        self.pvs = self.pcas_manager.pvs[pvinfo.port]
        self.pcas_manager.pvf[pvinfo.name] = pv
        self.pcas_manager.pvs[pvinfo.port][basename] = pv
        return pv

    def initAccessSecurityFile(self, filename, **subst):
        """
        Load access security configuration file

        :param filename: [str] Name of the access security configuration file
        :param kwargs: Substitute macros
        """
        macro = ','.join(['%s=%s' % (k, v) for k, v in subst.items()])
        pcaspy.asInitFile(filename, macro)
        pcaspy.asCaStart()

    def process(self, time):
        try:
            pcaspy.process(time)
        except AttributeError:
            pass  # happens sometimes when exiting


class CADriver(pcaspy.Driver):
    # Be sure to differentiate this driver in case the user uses
    # another pcaspy-based program in this session
    port = 'ECLIcas'

    def __init__(self, pvmanager, pvs):
        self.pcas_manager = pcaspy.driver.manager
        self.pvs = pvs
        super(CADriver, self).__init__()

    def check_pvs(self):
        # original driver did not support adding PVs
        for reason, pv in self.pcas_manager.pvs[self.port].items():
            #print('reason is', reason, 'pv is', pv)
            if reason not in self.pvDB:
                data = pcaspy.driver.Data()
                data.value = pv.info.value
                self.pvDB[reason] = data

    def write(self, pv, value):
        """
        Callback indicating that the PV was written to
        Return True to accept new value
        """
        capv = self.pvs[pv]
        if capv.written_to(value):
            self.setParam(pv, value)
            return True
        else:
            return False


class PVManager(object):
    def __init__(self, prefix):
        self.prefix = prefix
        self.thread = None

        self.server = CAServer()
        self.driver = None

    @property
    def pvs(self):
        return self.server.pvs

    def add_pv(self, pvname, write_callback=None, **kwargs):

        kwargs['port'] = CADriver.port

        pv = self.server._create_pv(self.prefix, pvname, kwargs)
        if self.driver is None:
            self.driver = CADriver(self, self.server.pvs)
        else:
            self.driver.check_pvs()

        pv.driver = self.driver
        return pv

    def run(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = ServerThread(self.server)
            self.thread.setDaemon(True)
            self.thread.start()
