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
import threading

# pcaspy
import pcaspy
from pcaspy import SimplePV as pcasPV
from pcaspy.tools import ServerThread

from . import CAPVBadValue

logger = logging.getLogger('ECLI.cas')


class CAPV(pcasPV):
    """
    Simple wrapper around pcasPV/SimplePV to add write callback
    functionality, and a simple way to update the value directly
    from the PV instance (see set_value)
    """
    ASYN_OFF = 0
    ASYN_CHECK = 1
    ASYN_START = 2

    def __init__(self, prefix, basename, pvinfo, **kwargs):
        name = '%s%s' % (prefix, basename)
        self.prefix = prefix
        self.basename = basename
        self.full_name = '%s%s' % (prefix, basename)

        pcasPV.__init__(self, name, pvinfo, **kwargs)
        self._write_callbacks = {}
        self._asyn_callbacks = {}

    def add_write_callback(self, fcn, **kwargs):
        """
        Callback when value is written to
        """
        assert(hasattr(fcn, '__call__'))
        self._write_callbacks[fcn] = kwargs

    def remove_write_callback(self, fcn):
        del self._write_callbacks[fcn]

    def add_asyn_callback(self, fcn, **kwargs):
        """
        With asynchronous PVs, the value is first checked
        by the write callback, and then processing should
        start when the asyn callback takes place.
        """
        assert(hasattr(fcn, '__call__'))
        self._asyn_callbacks[fcn] = kwargs

    def remove_asyn_callback(self, fcn):
        del self._asyn_callbacks[fcn]

    def check_value(self, value, asyn=None, raise_exception=False):
        """
        Callback from CAS Driver -- runs all callbacks, accepting
        the new value only if CAPVBadValue is not raised during
        any of the callbacks
        """
        for cb, kwargs in self._write_callbacks.items():
            try:
                cb(pv=self, pvname=self.name, value=value, asyn=asyn,
                   **kwargs)
            except CAPVBadValue:
                if raise_exception:
                    raise
                return False
            except:
                logger.debug('Unhandled exception during PV=%s write' % self.basename,
                             exc_info=True)
                if raise_exception:
                    raise

        return True

    def _run_asyn_callbacks(self, value, asyn_status):
        """
        Asyn callbacks
        """
        success = False

        for cb, kwargs in self._asyn_callbacks.items():
            try:
                cb(pv=self, pvname=self.name, value=value, asyn=asyn_status,
                   **kwargs)
            except:
                logger.debug('Unhandled exception during PV=%s asyn processing' % self.basename,
                             exc_info=True)
            else:
                success = True

        if self._asyn_callbacks and not success:
            # If none of the callbacks completed properly, then just outright
            # finish the asyn processing
            self.asyn_completed()

        return success

    def get_value(self):
        reason = self.basename
        return self.driver.pvDB[reason].value

    def set_value(self, value, check=True):
        """
        Update the PV to have a new value
        """
        if check:
            try:
                self.check_value(value, raise_exception=True)
            except Exception as ex:
                raise ValueError('Value=%s rejected: (%s) %s' %
                                 (value, ex.__class__.__name__, ex))

        self.post_update(value)
        return True

    # properties aren't working with SWIG for some reason?
    value = property(get_value, set_value, doc='PV value')

    def post_update(self, value=None):
        driver = self.driver
        reason = self.basename
        db_entry = driver.pvDB[reason]

        if value is not None:
            if pcaspy.__version__ <= (0, 4, 1):
                # pcaspy issue #5 -> alarm/value may not be updated
                db_entry.value = None
            driver.setParam(self.basename, value)

        if db_entry.flag and self.info.scan == 0:
            self.updateValue(db_entry)
            db_entry.flag = False

    def _write_value(self, gdd_value, asyn=None):
        value = gdd_value.get()
        success = self.check_value(value, asyn=asyn)
        if success:
            self.driver.setParam(self.basename, value)

        value = self.driver.getParamDB(self.info.reason)

        if not success:
            value.severity = pcaspy.Severity.INVALID_ALARM
            value.alarm = pcaspy.Alarm.WRITE_ALARM
        else:
            self.updateValue(value)

        return success

    def write(self, context, value):
        """
        Synchronous write of new value (or if CAS does not have
        WRITENOTIFY support)
        """
        # delegate asynchronous write to python writeNotify method
        # only if writeNotify not present in C++ library
        if not pcaspy.EPICS_HAS_WRITENOTIFY and self.info.asyn:
            return self.writeNotify(context, value)
        else:
            self._write_value(value, asyn=self.ASYN_OFF)
            return pcaspy.S_casApp_success

    def writeNotify(self, context, gdd_value):
        """
        Async write of new value with the context
        """
        success = self._write_value(gdd_value, self.ASYN_CHECK)
        # do asynchronous only if PV supports
        if success and self.info.asyn:
            # async write will finish later
            self.startAsyncWrite(context)

            self._run_asyn_callbacks(gdd_value.get(), self.ASYN_START)
            return pcaspy.S_casApp_asyncCompletion
        elif self.hasAsyncWrite():
            return pcaspy.S_casApp_postponeAsyncIO
        else:
            return pcaspy.S_casApp_success

    def asyn_completed(self):
        """
        Notify the driver that, as an asyn record,
        processing has completed
        """
        if self.info.asyn:
            self.endAsyncWrite(pcaspy.S_casApp_success)


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
        logger.debug('create pv %s %s' % (basename, pvinfo))
        pvinfo = pcaspy.PVInfo(pvinfo)
        pvinfo.reason = basename
        pvinfo.name = '%s%s' % (prefix, basename)

        if pvinfo.port not in self.pcas_manager.pvs:
            self.pcas_manager.pvs[pvinfo.port] = {}

        self.pvs = self.pcas_manager.pvs[pvinfo.port]

        if basename in self.pvs or pvinfo.name in self.pcas_manager.pvf:
            raise ValueError('PV %s already exists' % pvinfo.name)

        pv = CAPV(prefix, basename, pvinfo)

        self.pcas_manager.pvf[pvinfo.name] = pv
        self.pvs[basename] = pv
        return pv

    def _remove_pv(self, basename):
        """
        :param basename: basename, not including prefix
        :type basename: str
        """
        logger.debug('remove pv %s' % (basename, ))

        pvi = self.pvs[basename]
        pvinfo = pvi.info

        del self.pvs[basename]
        del self.pcas_manager.pvf[pvinfo.name]

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
        if capv.check_value(value):
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

    def remove_pv(self, pvname):
        return self.server._remove_pv(pvname)

    def add_pv(self, pvname, write_callback=None, **kwargs):
        kwargs['port'] = CADriver.port

        pv = self.server._create_pv(self.prefix, pvname, kwargs)
        if self.driver is None:
            self.driver = CADriver(self, self.server.pvs)
        else:
            self.driver.check_pvs()

        if write_callback is not None:
            assert(hasattr(write_callback, '__call__'))
            pv._write_callbacks.add(write_callback)

        pv.driver = self.driver
        return pv

    def run(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = ServerThread(self.server)
            self.thread.setDaemon(True)
            self.thread.start()

    def stop(self, join=True):
        if self.thread is not None:
            self.thread.stop()
            if join:
                self.thread.join()

            print('CAS thread finished')
