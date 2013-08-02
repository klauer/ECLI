# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_util.conditional_monitor` -- PV monitor utility
==========================================================

.. module:: ecli_util.conditional_monitor
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import sys
import time
import logging

import epics
from .errors import TimeoutError


class ConditionalMonitor(object):
    """
    Monitors a PV until one of several conditions occur:
        1. Ctrl-C is hit
        2. desired_value is reached (if numeric, within desired_epsilon)
        3. The PV stop_condition_pv changes
            a. If stop_pv_value is set, then it waits for this condition
            b. Otherwise, when the pv changes, the monitor will stop
        4. The timeout value is reached
        5. The timeout event is triggered (a threading.Event instance)
        6. The update callback function returns False

    Stop condition value can be a tuple/list, such that the full set of
    conditions should be followed in order.
    """
    def __init__(self, pv,
                 desired_value=None, desired_epsilon=1e-5,
                 stop_condition_pv=None, stop_pv_value=None,
                 wait=False, stop_index=0, timeout=None, use_type=None,
                 stop_event=None, connection_timeout=2.0,
                 pv_timeout=1.0, poll_rate=0.01, update_cb=None,
                 print_updates=False, print_file=sys.stdout):

        self._pv_timeout = pv_timeout
        self._stop_event = stop_event
        self._timeout = timeout
        self._use_type = use_type
        self._update_cb = update_cb
        self._stop_cb = None
        self._stop_pv = None
        self._poll_rate = poll_rate
        self._aborted = False

        self._print_updates = print_updates
        self._print_file = print_file

        if isinstance(stop_pv_value, (list, tuple)):
            self._stop_value = list(stop_pv_value)
            self._stop_index = stop_index
        else:
            self._stop_index = None
            self._stop_value = stop_pv_value

        self._running = False
        self._desired_value = desired_value

        self._desired_epsilon = desired_epsilon
        self._pv_name = pv
        self._pv = epics.PV(pv, connection_timeout=self._pv_timeout)
        if self._pv.status != 1:
            logging.error('Failed to connect to %s' % pv)
            return

        self._pv.add_callback(callback=self.value_updated)
        self._running = True

        if stop_condition_pv is not None:
            self._stop_pv = epics.PV(
                stop_condition_pv, connection_timeout=self._pv_timeout)
            if self._stop_pv.status == 1:
                self._stop_pv.add_callback(callback=self.stop_updated)
            else:
                logging.error('Failed to connect to %s' % stop_condition_pv)
                self._stop_pv = None

        self._pv.run_callbacks()
        if self._stop_pv:
            self._stop_pv.run_callbacks()

        if wait:
            self.wait()

    @property
    def pv(self):
        """The main PV"""
        return self._pv

    @property
    def stop_pv(self):
        """The PV to monitor for a stop condition"""
        return self._stop_pv

    @property
    def desired_value(self):
        """The desired value to reach, after which the monitor can stop"""
        return self._desired_value

    @property
    def desired_epsilon(self):
        """The factor by which desired_value can differ from the actual value"""
        return self._desired_epsilon

    def wait(self):
        """
        Waits for the conditions in ConditionalMonitor.__doc__

        Raises TimeoutError
        """
        try:
            start_time = time.time()
            use_timeout = self._timeout is not None and self._timeout > 0.0
            while self._running:
                epics.ca.poll()
                time.sleep(self._poll_rate)
                elapsed = time.time() - start_time

                if use_timeout and elapsed > self._timeout:
                    logging.error(
                        'ConditionalMonitor of %s timed out' % self._pv.pvname)
                    self.stop()
                    raise TimeoutError(
                        'ConditionalMonitor of %s timed out' % self._pv.pvname)
                elif self._stop_event is not None and self._stop_event.is_set():
                    logging.info('%s cancelled' % self)
                    self.stop()
                    break
        except KeyboardInterrupt:
            logging.info('%s cancelled (ctrl-c)' % self)
            self.stop()
            self._aborted = True

    @property
    def aborted(self):
        '''
        Was the monitor cancelled?
        '''
        return self._aborted

    def stop(self):
        """
        Stop monitoring and waiting.
        """
        if self._pv is not None:
            self._pv.clear_callbacks()
            self._pv = None

        if self._stop_pv is not None:
            self._stop_pv.clear_callbacks()
            self._stop_pv = None

        self._running = False

    def value_updated(self, timestamp=None, pvname=None, value=None,
                      char_value=None, **kwargs):
        """
        PV value updated callback
        """
        if self._print_updates > 0:
            print('%s\t%s\t%s' % (epics.pv.fmt_time(timestamp), pvname, value),
                  file=self._print_file)

        if not self._running:
            return
        if self._update_cb is not None:
            try:
                update_ret = self._update_cb(pvname=pvname, value=value,
                                             timestamp=timestamp, **kwargs)
            except Exception as ex:
                logging.error('Update callback function failed: (%s) %s' % (
                    ex.__class__.__name__, ex))

            if update_ret is False:
                self.stop()
                return

        if self._desired_value is not None:
            use_type = self._use_type
            if use_type in (int, float, None):
                try:
                    if use_type == int:
                        delta = abs(int(value) - int(self._desired_value))
                    else:
                        delta = abs(float(value) - self._desired_value)
                except:
                    if value == self._desired_value:
                        self.stop()
                else:
                    if delta <= self._desired_epsilon:
                        self.stop()
            elif use_type in (str, ):
                if char_value == self._desired_value:
                    self.stop()
            else:
                if use_type(value) == self._desired_value:
                    self.stop()

    def stop_updated(self, pvname=None, value=None, char_value=None, **kwargs):
        """
        Stop PV value updated callback
        """
        logging.debug('ConditionalMonitor: stop updated %s=%s' % (
            pvname, value))
        stop_index = self._stop_index

        if stop_index is None:
            stop_value = self._stop_value
        else:
            if stop_index >= len(self._stop_value):
                self.stop()
                return

            stop_value = self._stop_value[stop_index]

        use_type = self._use_type
        if ((value == stop_value or stop_value is None)
                or (use_type is not None and use_type(value) == value)
                or (isinstance(stop_value, str) and stop_value == char_value)):
            if stop_index is not None:
                self._stop_index += 1
                if self._stop_index < len(self._stop_value):
                    return

            logging.info('%s stopped: %s = %s' % (self, pvname, value))
            self.stop()

    def __str__(self):
        return 'ConditionalMonitor(pv=%s)' % (self._pv_name, )
