# -*-# coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_stepscan` -- PyEpics StepScan extension
==================================================

.. module:: ecli_stepscan
   :synopsis: PyEpics StepScan plugin for ECLI
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import sys
import time
import logging
import threading

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import ECLIExport
from ecli_util import get_plugin
from ecli_util.magic_args import (ecli_magic_args, argument)

import stepscan
import numpy as np

logger = logging.getLogger('ECLI.StepScan')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScans, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScans)


class ECLIPositioner(stepscan.Positioner):
    '''
    Modification of the basic StepScan positioner to add movement
    time statistics
    '''

    def __init__(self, *args, **kwargs):
        super(ECLIPositioner, self).__init__(*args, **kwargs)

        self.move_time = 0

    def move_to_pos(self, i, wait=False, timeout=600):
        """move to i-th position in positioner array"""
        def move_completed(**kws):
            elapsed = time.time() - start_move
            self.done = True
            self.move_time += elapsed

        if self.array is None:
            return
        elif not self.pv.connected:
            if not self.pv.wait_for_connection():
                return

        start_move = time.time()
        self.done = False
        # TODO this was here for piezo_motion bug, still necessary?
        #      stepscan does wait=False then wait=True move prior to
        #      scanning which complicates things
        #if i > 0 and self.pv.get() == self.array[i]:
        #    self.done = True
        #    return not self.done

        self.pv.put(self.array[i], callback=move_completed)
        time.sleep(1.e-4)
        if wait:
            try:
                t0 = time.time()
                while not self.done and (time.time() - t0) < timeout:
                    time.sleep(1.e-4)
            except KeyboardInterrupt:
                pass

            # TODO for some reason, a value of True indicates failure
            #      according to stepscan
            return not self.done


def get_grid_point(dim, cpt):
    """
    In, for example, a 10x10 scan, there are 100 points.
    This returns which point in the grid linear point x corresponds to
    """
    d = 1
    grid_pt = []
    for di in dim:
        grid_pt.append(int(cpt / d) % di)
        d *= di

    return tuple(grid_pt)


def fix_dimensions(d):
    """
    Strips off any final 1s in a dimension array
    """
    d = list(d)
    while d and d[-1] == 1:
        d = d[:-1]
    return d


def calc_ndim(dim):
    """
    Calculate the number of dimensions given a dimension tuple
    """
    return len(fix_dimensions(dim))


class ECLIScans(ECLIPlugin):
    """
    PyEpics scan engine plugin for ECLI

    This class doubles as the scan's scan messenger, which
    monitors a PyEpics stepscan and runs callbacks in a
    separate thread at
        1. pre-scan
        2. during each point of the scan
        3. abort/post-scan
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    CB_PRE_SCAN = 'PRE_SCAN'
    CB_SCAN_PAUSE = 'PAUSED'
    CB_SCAN_STEP = 'STEP'
    CB_SCAN_ABORT = 'ABORT'
    CB_POST_SCAN = 'POST_SCAN'
    CB_SAVE_PATH = 'SAVE_PATH'
    _callbacks = [CB_PRE_SCAN,
                  CB_SCAN_PAUSE,
                  CB_SCAN_STEP,
                  CB_SCAN_ABORT,
                  CB_POST_SCAN,

                  CB_SAVE_PATH,
                  ]
    # scan_time_pv = traitlets.Unicode(u'E1:Scans:scan1.DDLY', config=True) #
    # TODO
    detectors = traitlets.List(traitlets.Unicode,
                               default_value=[], config=True)
    trigger_detectors = traitlets.Dict(config=True)
    pos_settle_time = traitlets.Float(default_value=0.05, config=True)
    det_settle_time = traitlets.Float(default_value=0.10, config=True)
    extra_pvs = traitlets.List(traitlets.Unicode, config=True)

    def __init__(self, shell, config):
        self._detectors = []
        self._scan = None
        self._last_point = 0
        self._scan_number = 0
        self._update_lock = threading.Lock()

        super(ECLIScans, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI Scan plugin')

    @property
    def logger(self):
        return logger

    def _set_scan(self, scan):
        old_scan = self._scan
        if old_scan == scan:
            return
        elif old_scan is not None:
            old_scan.pre_scan_methods.remove(self.pre_scan)
            old_scan.post_scan_methods.remove(self.post_scan)

        if scan is not None:
            self._scan = scan
            scan.pre_scan_methods.append(self.pre_scan)
            scan.post_scan_methods.append(self.post_scan)
            if hasattr(scan.messenger, 'detached'):
                if hasattr(scan.messenger.detached, '__call__'):
                    scan.messenger.detached(scan=scan)

            scan.messenger = self

    def _get_scan(self):
        return self._scan

    scan = property(_get_scan, _set_scan)

    def set_min_scan_number(self, num):
        """
        Each archiver extension should call this function with its last
        used scan number.

        Since extensions that save scan data identify the scan by number,
        and there can be more than one extension saving data, this is used
        to avoid conflicting scan numbers.
        """
        num -= 1  # will be incremented the next scan

        if num > self._scan_number:
            self._scan_number = num

    def _update(self, scan=None, cpt=0, **kwargs):
        """
        Callback from PyEpics scan record, indicating a new point
        is available. If the data processing takes a long time,
        update may only get called every other point, but this
        function is aware of that and ensures there's a 'single_step'
        callback for each point.
        """
        if scan is not self._scan:
            return

        with self._update_lock:
            point_diff = cpt - self._last_point
            if point_diff <= 0:
                return
            elif point_diff > 1:
                # Some missed points
                last_point = self._last_point
                self._last_point = cpt
                # Report each of the missed points
                for i in xrange(last_point + 1, cpt + 1):
                    self.single_step(scan, i)
            else:
                self._last_point = cpt
                self.single_step(scan, cpt)

    __call__ = _update

    def detached(self, scan=None):
        if scan is not self._scan:
            return

        logger.debug('detached from scan: %s' % scan)

    def pre_scan(self, scan=None):
        """
        Pre-scan callback from stepscan
        """
        self.scan = scan

        mca_detectors = [c for c in scan.counters
                         if isinstance(c, stepscan.detectors.McaDetector)]

        self._last_point = 0
        info = scan.ecli_info
        self.run_callback(self.CB_PRE_SCAN, scan=self.scan,
                          mca_detectors=mca_detectors,
                          handle_exceptions=False,
                          **info)

    def post_scan(self, scan=None):
        """
        Post-scan callback from stepscan
        """
        scan = self._scan
        if scan is None:
            return

        if scan.abort:
            self.run_callback(self.CB_SCAN_ABORT, scan=scan)
        else:
            # It's possible for the messenger to miss a point at the end
            # of the scan:
            if (scan.npts - self._last_point) > 0:
                self._update(scan=scan, cpt=scan.npts)

        info = scan.ecli_info

        self.run_callback(self.CB_POST_SCAN, scan=scan, abort=scan.abort,
                          **info)

    def single_step(self, scan, point):
        """
        Single step (per-point) callback from stepscan
        """
        info = scan.ecli_info
        dim = info['dimensions']
        array_idx = point - 1
        self.run_callback(self.CB_SCAN_STEP,
                          show_traceback=sys.stdout,
                          scan=scan, point=point, array_idx=array_idx,
                          grid_point=get_grid_point(dim, array_idx), **info)

    def _detectors_changed(self, *args):
        logger.info('Detector list updated: %s' % self.detectors)

        del self._detectors[:]
        for alias in self.detectors:
            pv = util.expand_alias(alias)
            try:
                det = stepscan.get_detector(pv, label=alias)
            except Exception as ex:
                logger.error('Bad detector: %s (%s) %s'
                             % (pv, ex.__class__.__name__, ex))
            except KeyboardInterrupt:
                logger.warning('Skipping detector list entry: %s' % pv)
            else:
                self._detectors.append(det)

    @ECLIExport
    def scan_save(self, path):
        """
        Notifies all scan file writers where to write the data

        .. note:: file extensions will be added by the plugin
        """
        self.run_callback(self.CB_SAVE_PATH, path=path)

    @ECLIExport
    def scan_run(self, positioners, dwell_time, move_back=True, command='', dimensions=None,
                 breakpoints=[], counters=[], detectors=[], triggers=[], run=True,
                 **kwargs):
        """
        Perform a generic scan

        :param positioners: Motors to scan, with absolute position arrays
                            previously set
        :param dwell_time: Seconds at each point
        :param move_back: Move all positioners back to their starting position
                          post scan
        :param command: the command-line command used to start the scan
        :param dimensions: the scan dimensions
        :param counters: additional counters not normally included (can be a PV name)
        :param detectors: additional detectors not normally included
        :param triggers: additional triggers not normally included (can be a PV name)
        :param run: run the scan (or just return one ready to run)
        :param kwargs: passed onto the scan's ECLI info
        :returns: the scan instance
        """
        array_shapes = set([pos.array.shape for pos in positioners])
        if len(array_shapes) != 1:
            raise ValueError('Positioners must have the same position array dimensions')

        data_points = np.size(positioners[0].array)

        self.scan = sc = stepscan.StepScan()
        if dimensions is None or not isinstance(dimensions, (list, tuple)):
            dimensions = (data_points, )

        for positioner in positioners:
            sc.add_positioner(positioner)

        for counter in counters:
            sc.add_counter(counter)

        for trigger in triggers:
            sc.add_trigger(trigger)

        motor_plugin = get_plugin('ECLIMotor')
        for motor in motor_plugin.motor_list:
            motor_rec = motor_plugin.get_motor(motor)
            sc.add_extra_pvs([(motor, motor_rec.PV('RBV'))])

        for pv in self.extra_pvs:
            name = self.core.get_aliased_name(pv)
            sc.add_extra_pvs([(name, pv)])

        for det_pv in self.detectors + list(detectors):
            det = stepscan.get_detector(util.expand_alias(det_pv), label=det_pv)
            if det is None:
                logger.error('Scan %s invalid detector: %s' % (sc, det_pv))
                return None
            logger.debug('Scan %s added detector: %s' % (sc, det))
            sc.add_detector(det)

            # TODO bug report - hardware triggered detectors
            if det.trigger is not None:
                sc.triggers.remove(det.trigger)
                if det_pv in self.trigger_detectors:
                    trigger_value = self.trigger_detectors[det_pv]
                    #print('adding trigger', det_pv, trigger_value)
                    logger.debug('Added detector trigger: %s = %s' %
                                 (det.trigger, trigger_value))
                    sc.add_trigger(det.trigger, value=trigger_value)

        # TODO StepScan bug report:
        #   add_trigger needs to check for None (as in SimpleDetector)
        sc.triggers = [trigger for trigger in sc.triggers
                       if trigger is not None]

        sc.set_dwelltime(dwell_time)

        start_pos = [pos.current() for pos in positioners]

        self._scan_number += 1
        sc.ecli_info = {'command': command,
                        'scan_number': self._scan_number,
                        'dimensions': dimensions,
                        'ndim': calc_ndim(dimensions),
                        'scanning': [pos.label for pos in positioners],
                        }

        if hasattr(sc, 'timestamps'):
            # Added timestamps in ECLI stepscan fork
            sc.ecli_info['timestamps'] = sc.timestamps
            sc.get_timestamp = lambda i: sc.timestamps[i]
        else:
            sc.get_timestamp = lambda i: None

        sc.ecli_info.update(kwargs)

        sc.pos_settle_time = self.pos_settle_time
        sc.det_settle_time = self.det_settle_time

        if not run:
            return sc

        # TODO: check all PVs prior to scan
        # Run the scan
        try:
            sc.run(None)
        except Exception as ex:
            if sc.message_thread is not None:
                sc.message_thread.cpt = None
            logger.error('Scan failed: (%s) %s' % (ex.__class__.__name__, ex))
        finally:
            # Wait for the message thread to catch up
            if sc.message_thread is not None:
                sc.message_thread.join(1.0)

        if move_back:
            # Move the positioners back to their starting positions
            for pos, start in zip(positioners, start_pos):
                logger.info('Moving %s back to the starting position %g' %
                            (pos, start))
                try:
                    pos.move_to(start, wait=True)
                except KeyboardInterrupt:
                    print('%s move to %g cancelled (current position=%s)' %
                          (pos.label, start, pos.current()))

        # Make a simple dictionary holding the scan data
        data = {}
        for counter in sc.counters:
            data[counter.label] = counter.buff

        # And export that data back to the user namespace as `scan_data`
        self.core.set_variable('scan_data', data)
        return sc

    @ECLIExport
    def scan_1d(self, motor='', start=0.0, end=0.0, data_points=0, dwell_time=0.0, relative=True,
                counters=[]):
        """Perform a 1D scan of motor in [start, end] of data_points

        :param motor: Motor to scan
        :param start: Relative scan starting position for motor1
        :param end: Relative scan ending position for motor1
        :param data_points: Number of data points to acquire
        :param dwell_time: Seconds at each point
        """
        try:
            motor = AliasedPV(motor)
            start = util.check_float(start)
            end = util.check_float(end)
            data_points = util.check_int(data_points)
            dwell_time = util.check_float(dwell_time)
            relative = util.check_bool(relative)
        except Exception as ex:
            print('Scan argument check failed: %s' % (ex, ))
            return False

        if relative:
            scan_type = 'dscan'
        else:
            scan_type = 'ascan'

        m_name = self.core.get_aliased_name(motor)
        command = '%(scan_type)s  %(m_name)s  %(start)g %(end)g  %(data_points)d %(dwell_time)g' % \
                  locals()

        pos0 = ECLIPositioner(motor, label=m_name)
        start_pos = pos0.current()
        pos0.array = np.linspace(start, end, data_points)
        if relative:
            pos0.array += start_pos

        print('Scan: %s from %g to %g (%d data points)' %
              (motor, start, end, data_points))

        positioners = [pos0]

        mct = stepscan.MotorCounter(motor, label=m_name)

        counters = list(counters)
        counters.insert(0, mct)
        return self.scan_run(positioners, dwell_time, command=command,
                             counters=counters, detectors=[], dimensions=(data_points, ),
                             )

    @ECLIExport
    def ascan(self, motor='', start='', end='', data_points=0, dwell_time=0.0, **kwargs):
        """Perform a 1D scan of motor in [start, end] of data_points

        :param motor: Motor to scan
        :param start: Absolute scan starting position for `motor`
        :param end: Absolute scan ending position for `motor`
        :param data_points: Number of data points to acquire
        :param dwell_time: Seconds at each point
        """
        return self.scan_1d(motor=motor, start=start, end=end, data_points=data_points,
                            dwell_time=dwell_time, relative=False,
                            **kwargs)

    @ECLIExport
    def dscan(self, motor='', start='', end='', data_points=0, dwell_time=0.0, **kwargs):
        """Perform a 1D scan of motor in [start, end] of data_points

        :param motor: Motor to scan
        :param start: Relative scan starting position for `motor`
        :param end: Relative scan ending position for `motor`
        :param data_points: Number of data points to acquire
        :param dwell_time: Seconds at each point
        """
        return self.scan_1d(motor=motor, start=start, end=end, data_points=data_points,
                            dwell_time=dwell_time, relative=True,
                            **kwargs)

    @ECLIExport
    def scan_nd(self, motors, dwell_time, relative=True):
        # TODO
        raise NotImplementedError

    @ECLIExport
    def scan_2d(self, motor1='', start1=0.0, end1=0.0, points1=0,
                motor2='', start2=0.0, end2=0.0, points2=0,
                dwell_time=0.0, relative=True):
        """Perform a 2D scan of dimension (points1, points2):
            motor1 in [start1, end1], with points1 data points (inner loop, fast)
            motor2 in [start2, end2], with points2 data points (outer loop, slow)

        Scan relative to the starting position (dmesh) or utilizing absolute
        positions (amesh)::
            for motor2 = start2 to end2, step (end2-start2) / points2:
                for motor1 = start1 to end1, step (end1-start1) / points1:
                    wait for [time] secs
                    take data point

        :param motor1: Motor to scan
        :param start1: Relative scan starting position for motor1
        :param end1: Relative scan ending position for motor1
        :param points1: Number of data points for motor1

        :param motor2: Motor 2 to scan
        :param start2: Relative scan starting position for motor2
        :param points2: Number of data points for motor2

        :param end2: Relative scan ending position for motor2
        :param data_points: Number of data points to acquire
        :param dwell_time: Seconds at each point
        :returns: the scan instance
        """
        # TODO merge this into scan_nd
        try:
            motor1 = AliasedPV(motor1)
            start1 = util.check_float(start1)
            end1 = util.check_float(end1)
            points1 = util.check_int(points1)

            motor2 = AliasedPV(motor2)
            start2 = util.check_float(start2)
            end2 = util.check_float(end2)
            points2 = util.check_int(points2)

            dwell_time = util.check_float(dwell_time)
            relative = util.check_bool(relative)
        except Exception as ex:
            print('Scan argument check failed: %s' % (ex, ))
            return False

        if relative:
            scan_type = 'dmesh'
        else:
            scan_type = 'amesh'

        m1_name = self.core.get_aliased_name(motor1)
        m2_name = self.core.get_aliased_name(motor2)

        command = '%(scan_type)s  %(m1_name)s  %(start1)g %(end1)g  %(points1)d  %(m2_name)s  %(start2)g %(end2)g  %(points2)d  %(dwell_time)g' % \
                  locals()

        # Positioner 1 - 'fast' inner loop
        pos1 = ECLIPositioner(motor1, label=m1_name)
        pos1.array = np.array(points2 * [np.linspace(start1, end1, points1)]).flatten()
        if relative:
            pos1.array += pos1.current()

        # Positioner 2 - 'slow' outer loop
        pos2 = ECLIPositioner(motor2, label=m2_name)
        pos2.array = np.array([[i] * points1
                              for i in np.linspace(start2, end2, points2)]).flatten()
        if relative:
            pos2.array += pos2.current()

        dimensions = (points1, points2)
        print('Inner: %s from %g to %g (%d data points)' %
              (motor1, start1, end1, points1))
        print('Outer: %s from %g to %g (%d data points)' %
              (motor2, start2, end2, points2))
        print('Dimensions: %s (total points=%d)' % (dimensions, points1 * points2))

        positioners = (pos1, pos2)

        counters = [stepscan.MotorCounter(motor1, label=m1_name),
                    stepscan.MotorCounter(motor2, label=m2_name),
                    ]

        return self.scan_run(positioners, dwell_time, command=command,
                             counters=counters, detectors=[], dimensions=dimensions,
                             )

    @ECLIExport
    def amesh(self,
              motor1='', start1=0.0, end1=0.0, points1=0,
              motor2='', start2=0.0, end2=0.0, points2=0,
              dwell_time=0.0):
        # Convenience function -- absolute 2D scan
        return self.scan_2d(relative=False,
                            motor1=motor1, start1=start1, end1=end1, points1=points1,
                            motor2=motor2, start2=start2, end2=end2, points2=points2,
                            dwell_time=dwell_time)

    @ECLIExport
    def dmesh(self,
              motor1='', start1=0.0, end1=0.0, points1=0,
              motor2='', start2=0.0, end2=0.0, points2=0,
              dwell_time=0.0):
        """Perform a 2D scan of dimension (points1, points2):
            motor1 in [start1, end1], with points1 data points (inner loop, fast)
            motor2 in [start2, end2], with points2 data points (outer loop, slow)

        Scan relative to the starting position (dmesh) or utilizing absolute
        positions (amesh)::
            for motor2 = start2 to end2, step (end2-start2) / points2:
                for motor1 = start1 to end1, step (end1-start1) / points1:
                    wait for [time] secs
                    take data point

        """
        # Convenience function -- relative 2D scan
        return self.scan_2d(relative=True,
                            motor1=motor1, start1=start1, end1=end1, points1=points1,
                            motor2=motor2, start2=start2, end2=end2, points2=points2,
                            dwell_time=dwell_time)

    @ECLIExport
    def scan_generic_2d(self, motor_x, motor_y, points_x, points_y, dwell_time=1.0, command=None,
                        relative=True, counters=[]):
        try:
            motor_x = AliasedPV(motor_x)
            motor_y = AliasedPV(motor_y)

            dwell_time = util.check_float(dwell_time)
        except Exception as ex:
            print('Scan argument check failed: %s' % (ex, ))
            return False

        mx_name = self.core.get_aliased_name(motor_x)
        my_name = self.core.get_aliased_name(motor_y)

        motorx = ECLIPositioner(motor_x, label=mx_name)
        motory = ECLIPositioner(motor_y, label=my_name)

        motorx.array = np.array(points_x)
        motory.array = np.array(points_y)

        if relative:
            motorx.array += motorx.current()
            motory.array += motory.current()

        if command is None:
            command = 'generic_2d  %s %s  %g' % (mx_name, my_name, dwell_time)

        data_points = len(motorx.array)

        positioners = [motorx, motory]

        counters = list(counters)
        counters.insert(0, stepscan.MotorCounter(motor_x, label=mx_name))
        counters.insert(1, stepscan.MotorCounter(motor_y, label=my_name))
        return self.scan_run(positioners, dwell_time, command=command,
                             counters=counters, detectors=[], dimensions=(data_points, ),
                             )

    mesh = amesh
    amesh.__doc__ = dmesh.__doc__


@ecli_magic_args(ECLIScans)
@argument('motor', type=AliasedPV,
          help='Motor to scan')
@argument('start', type=float,
          help='Relative scan starting position for motor1')
@argument('end', type=float,
          help='Relative scan ending position for motor1')
@argument('data_points', type=util.arg_value_range(min_=1),
          help='Number of data points to acquire')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
@argument('counters', type=AliasedPV, nargs='*',
          help='Additional counters to monitor')
def dscan(margs, self, args):
    """
    $ dscan motor relative_start relative_end data_points time
    $ ascan motor start end data_points time

    Scan relative to the starting position (dscan) or utilizing absolute
    positions (ascan). The positions are automatically calculated by EPICS
    from the amount of data points that are requested.
    """
    self.dscan(motor=args.motor, start=args.start, end=args.end,
               data_points=args.data_points, dwell_time=args.time,
               counters=args.counters)


@ecli_magic_args(ECLIScans)
@argument('motor', type=AliasedPV,
          help='Motor to scan')
@argument('start', type=float,
          help='Absolute starting position for motor1')
@argument('end', type=float,
          help='Absolute scan ending position for motor1')
@argument('data_points', type=util.arg_value_range(min_=1),
          help='Number of data points to acquire')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
@argument('counters', type=AliasedPV, nargs='*',
          help='Additional counters to monitor')
def ascan(margs, self, args):
    self.ascan(motor=args.motor, start=args.start, end=args.end,
               data_points=args.data_points, dwell_time=args.time,
               counters=args.counters)


@ecli_magic_args(ECLIScans)
@argument('motor1', type=AliasedPV,
          help='Motor to scan (1)')
@argument('start1', type=float,
          help='Relative scan starting position for motor1')
@argument('end1', type=float,
          help='Relative scan ending position for motor1')
@argument('points1', type=util.arg_value_range(min_=1),
          help='Number of points along (start1 to end1)')
@argument('motor2', type=AliasedPV,
          help='Motor to scan (2)')
@argument('start2', type=float,
          help='Relative scan starting position for motor2')
@argument('end2', type=float,
          help='Relative scan ending position for motor2')
@argument('points2', type=util.arg_value_range(min_=1, type_=int),
          help='Number of points along (start2 to end2)')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
def mesh(margs, self, args):
    """Perform a 2D scan of dimension (points1, points2):
        motor1 in [start1, end1], with points1 data points (inner loop, fast)
        motor2 in [start2, end2], with points2 data points (outer loop, slow)

    Scan relative to the starting position (dmesh) or utilizing absolute
    positions (amesh)::
        for motor2 = start2 to end2, step (end2-start2) / points2:
            for motor1 = start1 to end1, step (end1-start1) / points1:
                wait for [time] secs
                take data point

    """
    return self.amesh(motor1=args.motor1, start1=args.start1, end1=args.end1, points1=args.points1,
                      motor2=args.motor2, start2=args.start2, end2=args.end2, points2=args.points2,
                      dwell_time=args.time)

amesh = mesh


@ecli_magic_args(ECLIScans)
@argument('motor1', type=AliasedPV,
          help='Motor to scan (1)')
@argument('start1', type=float,
          help='Relative scan starting position for motor1')
@argument('end1', type=float,
          help='Relative scan ending position for motor1')
@argument('points1', type=util.arg_value_range(min_=1),
          help='Number of points along (start1 to end1)')
@argument('motor2', type=AliasedPV,
          help='Motor to scan (2)')
@argument('start2', type=float,
          help='Relative scan starting position for motor2')
@argument('end2', type=float,
          help='Relative scan ending position for motor2')
@argument('points2', type=util.arg_value_range(min_=1, type_=int),
          help='Number of points along (start2 to end2)')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
def dmesh(margs, self, args):
    """Perform a 2D scan of dimension (points1, points2):
        motor1 in [start1, end1], with points1 data points (inner loop, fast)
        motor2 in [start2, end2], with points2 data points (outer loop, slow)

    Scan relative to the starting position (dmesh) or utilizing absolute
    positions (amesh)::
        for motor2 = start2 to end2, step (end2-start2) / points2:
            for motor1 = start1 to end1, step (end1-start1) / points1:
                wait for [time] secs
                take data point

    """
    return self.dmesh(motor1=args.motor1, start1=args.start1, end1=args.end1, points1=args.points1,
                      motor2=args.motor2, start2=args.start2, end2=args.end2, points2=args.points2,
                      dwell_time=args.time)


def spiral_simple(x_range_egu, y_range_egu, dr_egu, nth):
    """
    Spiral scan pattern 1
    by Xiaojing Huang
    """
    r_max_egu = np.sqrt((x_range_egu / 2.) ** 2 + (y_range_egu / 2.) ** 2)
    num_ring = 1 + int(r_max_egu / dr_egu)

    half_x = x_range_egu / 2
    half_y = y_range_egu / 2

    x_points = []
    y_points = []
    for i_ring in range(1, num_ring + 2):
        radius_egu = i_ring * dr_egu
        angle_step = 2. * np.pi / (i_ring * nth)

        for i_angle in range(int(i_ring * nth)):
            angle = i_angle * angle_step
            x_egu = radius_egu * np.cos(angle)
            y_egu = radius_egu * np.sin(angle)
            if abs(x_egu) <= half_x and abs(y_egu) <= half_y:
                x_points.append(x_egu)
                y_points.append(y_egu)

    return x_points, y_points


def spiral_fermat(x_range_egu, y_range_egu, dr_egu, factor):
    """
    Fermat spiral scan pattern
    by Xiaojing Huang
    """
    phi = 137.508 * np.pi / 180.

    half_x = x_range_egu / 2
    half_y = y_range_egu / 2

    x_points, y_points = [], []

    diag = np.sqrt(x_range_egu ** 2 + y_range_egu ** 2)
    num_rings = int((1.5 * diag / dr_egu) ** 2)
    for i_ring in range(1, num_rings):
        radius_egu = np.sqrt(i_ring) * dr_egu / factor
        angle = phi * i_ring
        x_egu = radius_egu * np.cos(angle)
        y_egu = radius_egu * np.sin(angle)

        if abs(x_egu) <= half_x and abs(y_egu) <= half_y:
            x_points.append(x_egu)
            y_points.append(y_egu)

    return x_points, y_points


@ecli_magic_args(ECLIScans)
@argument('motorx', type=str,
          help='X motor to scan (inner)')
@argument('motory', type=str,
          help='Y motor to scan (outer)')
@argument('width', type=float,
          help='X width in motor EGUs')
@argument('height', type=float,
          help='Y height in motor EGUs')
@argument('ring_incr', type=float,
          help='Increment between rings')
@argument('first_points', type=int,
          help='Number of points in the first ring')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
def spiral(margs, self, args):
    """
    Simple spiral scan
    """
    px, py = spiral_simple(args.width, args.height, args.ring_incr, args.first_points)

    command = 'spiral  %s %s  %g %g  %g %d  %g' % (args.motorx, args.motory, args.width, args.height,
                                                   args.ring_incr, args.first_points, args.time)

    print("""Motors: %s %s (%g x %g)
Spiral scan 1 (r_incr %g inner points %d) (%d data points)""" %
          (args.motorx, args.motory, args.width, args.height,
           args.ring_incr, args.first_points, len(px)))

    return self.scan_generic_2d(args.motorx, args.motory, px, py, command=command)


@ecli_magic_args(ECLIScans)
@argument('motorx', type=str,
          help='X motor to scan (inner)')
@argument('motory', type=str,
          help='Y motor to scan (outer)')
@argument('width', type=float,
          help='X width in motor EGUs')
@argument('height', type=float,
          help='Y height in motor EGUs')
@argument('ring_incr', type=float,
          help='Increment between rings')
@argument('factor', type=float, default=1.529,
          help='Ring increment is divided by this')
@argument('time', type=util.arg_value_range(min_=0, inclusive=False,
                                            type_=float),
          help='Seconds at each point')
def fermat(margs, self, args):
    """
    Fermat spiral scan
    """

    px, py = spiral_fermat(args.width, args.height, args.ring_incr, args.factor)

    command = 'fermat  %s %s  %g %g  %g %g  %g' % (args.motorx, args.motory, args.width, args.height,
                                                   args.ring_incr, args.factor, args.time)

    print("""Motors: %s %s (%g x %g)
Fermat spiral scan (r_incr %g factor %g) (%d data points)""" %
          (args.motorx, args.motory, args.width, args.height,
           args.ring_incr, args.factor, len(px)))

    return self.scan_generic_2d(args.motorx, args.motory, px, py, command=command)


@ecli_magic_args(ECLIScans)
@argument('filename', type=str,
          help='Base of filename')
def scan_save(margs, self, args):
    """
    Notifies all scan file writers where to write the data

    .. note:: file extensions will be added by the plugin
    """
    self.scan_save(args.filename)
