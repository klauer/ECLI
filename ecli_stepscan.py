# -*- coding: utf-8 -*-
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
from IPython.core.magic_arguments import (argument, magic_arguments,
                                          parse_argstring)

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util import ECLIError
from ecli_util.decorators import ECLIExport

import stepscan
import numpy as np

logger = logging.getLogger('ECLIStepScan')


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

        if self.array is None or not self.pv.connected:
            return

        start_move = time.time()
        self.done = False
        self.pv.put(self.array[i], callback=move_completed)
        time.sleep(1.e-4)
        if wait:
            t0 = time.time()
            while not self.done and (time.time() - t0) < timeout:
                time.sleep(1.e-4)


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
    while d[-1] == 1:
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
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    CB_PRE_SCAN = 'PRE_SCAN'
    CB_SCAN_PAUSE = 'PAUSED'
    CB_SCAN_STEP = 'STEP'
    CB_SCAN_ABORT = 'ABORT'
    CB_POST_SCAN = 'POST_SCAN'
    _callbacks = [CB_PRE_SCAN,
                  CB_SCAN_PAUSE,
                  CB_SCAN_STEP,
                  CB_SCAN_ABORT,
                  CB_POST_SCAN,
                  ]
    # scan_time_pv = traitlets.Unicode(u'E1:Scans:scan1.DDLY', config=True) #
    # TODO
    #detectors = traitlets.List(traitlets.Unicode,
    #                           default_value=[u'mca:mca1', u'IOC:m1'], config=True)
    detectors = traitlets.List(traitlets.Unicode,
                               default_value=[u'IOC:m1'], config=True)

    def __init__(self, shell, config):
        super(ECLIScans, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI Scan plugin')
        self._scan = None
        self._last_point = 0
        self._scan_number = 0
        self._update_lock = threading.Lock()

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIScans')

    @property
    def logger(self):
        return logger

    """
    Monitors a PyEpics stepscan and runs callbacks in a separate thread
    at
        1. pre-scan
        2. during each point of the scan
        3. abort/post-scan
    """
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

        print('detached from scan', scan)

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
            # print('abort scan detected')
        else:
            # It's possible for the messenger to miss a point at the end
            # of the scan:
            if (scan.npts - self._last_point) > 0:
                self._update(scan=scan, cpt=scan.npts)

        # print('post scan', scan)
        self.run_callback(self.CB_POST_SCAN, scan=scan, abort=scan.abort)

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
                          grid_point=get_grid_point(dim, point))

    def _detectors_changed(self, *args):
        print('Detector list updated: %s' % self.detectors)
        self._detectors = [stepscan.get_detector(d) for d in self.detectors]

# Commands #


@ECLIExport
def scan(positioners, dwell_time, move_back=True, command='', dimensions=None,
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

    plugin = ECLIScans.get_plugin()
    plugin.scan = sc = stepscan.StepScan()
    if dimensions is None or not isinstance(dimensions, (list, tuple)):
        dimensions = (data_points, )

    for det_pv in plugin.detectors:
        det = stepscan.get_detector(util.expand_alias(det_pv), label=det_pv)
        if det is None:
            logger.error('Invalid detector: %s' % det_pv)
            return None
        logger.debug('Added detector: %s' % det)
        sc.add_detector(det)
        logger.debug('Added detector trigger: %s' % det.trigger)
        sc.add_trigger(det.trigger)

    for positioner in positioners:
        sc.add_positioner(positioner)

    for counter in counters:
        sc.add_counter(counter)

    for detector in detectors:
        sc.add_detector(detector)

    for trigger in triggers:
        sc.add_trigger(trigger)

    sc.set_dwelltime(dwell_time)

    start_pos = [pos.current() for pos in positioners]

    plugin._scan_number += 1
    sc.ecli_info = {'command': command,
                    'scan_number': plugin._scan_number,
                    'dimensions': dimensions,
                    'ndim': calc_ndim(dimensions),
                    }
    sc.ecli_info.update(kwargs)

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
            sc.message_thread.join()

    if move_back:
        # Move the positioners back to their starting positions
        for pos, start in zip(positioners, start_pos):
            logger.info('Moving %s back to the starting position %g' %
                        (pos, start))
            pos.move_to(start, wait=True)

    # Make a simple dictionary holding the scan data
    data = {}
    for counter in sc.counters:
        data[counter.label] = counter.buff

    # And export that data back to the user namespace as `scan_data`
    core = get_core_plugin()
    core.set_variable('scan_data', data)
    return sc


# -- 1D scans
@ECLIExport
def scan_1d(motor='', start=0.0, end=0.0, data_points=0, dwell_time=0.0, relative=True):
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

    command = '%(scan_type)s  %(motor)s  %(start)g %(end)g  %(data_points)d %(dwell_time)g' % \
              locals()

    pos0 = ECLIPositioner(motor)
    start_pos = pos0.current()
    pos0.array = np.linspace(start, end, data_points)
    if relative:
        pos0.array += start_pos

    print('Scan: %s from %g to %g (%d data points)' %
         (motor, start, end, data_points))

    # TODO invalid PVs are not ignored **
    # scan.add_detector(stepscan.detectors.McaDetector('MLL:DXP:mca1',
    # use_full=True))

    positioners = [pos0]
    # additional counters TODO remove
    counters = (stepscan.MotorCounter('IOC:m1', label='m1'),
                stepscan.MotorCounter('IOC:m2', label='m2'),
                stepscan.MotorCounter('IOC:m3', label='m3'),
                stepscan.MotorCounter('IOC:m4', label='m4'),
                stepscan.MotorCounter('IOC:m5', label='m5'),
                stepscan.MotorCounter('IOC:m6', label='m6'))

    return scan(positioners, dwell_time, command=command,
                counters=counters, detectors=[], dimensions=(data_points, ),
                )


@ECLIExport
def ascan(motor='', start='', end='', data_points=0, dwell_time=0.0):
    """Perform a 1D scan of motor in [start, end] of data_points

    :param motor: Motor to scan
    :param start: Absolute scan starting position for `motor`
    :param end: Absolute scan ending position for `motor`
    :param data_points: Number of data points to acquire
    :param dwell_time: Seconds at each point
    """
    return scan_1d(motor=motor, start=start, end=end, data_points=data_points,
                   dwell_time=dwell_time, relative=False)


@ECLIExport
def dscan(motor='', start='', end='', data_points=0, dwell_time=0.0):
    """Perform a 1D scan of motor in [start, end] of data_points

    :param motor: Motor to scan
    :param start: Relative scan starting position for `motor`
    :param end: Relative scan ending position for `motor`
    :param data_points: Number of data points to acquire
    :param dwell_time: Seconds at each point
    """
    return scan_1d(motor=motor, start=start, end=end, data_points=data_points,
                   dwell_time=dwell_time, relative=True)


@magic_arguments()
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
def _dscan(self, arg):
    """
    $ dscan motor relative_start relative_end data_points time
    $ ascan motor start end data_points time

    Scan relative to the starting position (dscan) or utilizing absolute
    positions (ascan). The positions are automatically calculated by EPICS
    from the amount of data points that are requested.
    """
    args = parse_argstring(_dscan, arg)
    if args is None:
        return

    dscan(motor=args.motor, start=args.start, end=args.end,
           data_points=args.data_points, dwell_time=args.time)


@magic_arguments()
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
def _ascan(self, arg):
    args = parse_argstring(_ascan, arg)
    if args is None:
        return

    ascan(motor=args.motor, start=args.start, end=args.end,
           data_points=args.data_points, dwell_time=args.time)

ascan.__doc__ = dscan.__doc__


@ECLIExport
def scan_nd(motors, dwell_time, relative=True):
    # TODO
    raise NotImplementedError


# -- 2D scans
@ECLIExport
def scan_2d(motor1='', start1=0.0, end1=0.0, points1=0,
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

    command = '%(scan_type)s  %(motor1)s  %(start1)g %(end1)g  %(points1)d  %(motor2)s  %(start2)g %(end2)g  %(points2)d  %(dwell_time)g' % \
              locals()

    # Positioner 1 - 'fast' inner loop
    pos1 = ECLIPositioner(motor1)
    pos1.array = np.array(points2 * [np.linspace(start1, end1, points1)]).flatten()
    if relative:
        pos1.array += pos1.current()

    # Positioner 2 - 'slow' outer loop
    pos2 = ECLIPositioner(motor2)
    pos2.array = np.array([[i] * points2
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

    # additional counters TODO remove
    counters = (stepscan.MotorCounter('IOC:m1', label='m1'),
                stepscan.MotorCounter('IOC:m2', label='m2'),
                stepscan.MotorCounter('IOC:m3', label='m3'),
                stepscan.MotorCounter('IOC:m4', label='m4'),
                stepscan.MotorCounter('IOC:m5', label='m5'),
                stepscan.MotorCounter('IOC:m6', label='m6'))

    return scan(positioners, dwell_time, command=command,
                counters=counters, detectors=[], dimensions=dimensions,
                )

@magic_arguments()
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
def _mesh(self, arg):
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
    args = parse_argstring(_mesh, arg)
    if args is None:
        return

    return amesh(motor1=args.motor1, start1=args.start1, end1=args.end1, points1=args.points1,
                 motor2=args.motor2, start2=args.start2, end2=args.end2, points2=args.points2,
                 dwell_time=args.time)

_amesh = _mesh

@magic_arguments()
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
def _dmesh(self, arg):
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
    args = parse_argstring(_mesh, arg)
    if args is None:
        return

    return dmesh(motor1=args.motor1, start1=args.start1, end1=args.end1, points1=args.points1,
                 motor2=args.motor2, start2=args.start2, end2=args.end2, points2=args.points2,
                 dwell_time=args.time)


@ECLIExport
def amesh(motor1='', start1=0.0, end1=0.0, points1=0,
          motor2='', start2=0.0, end2=0.0, points2=0,
          dwell_time=0.0):
    # Convenience function
    return scan_2d(relative=False,
            motor1=motor1, start1=start1, end1=end1, points1=points1,
            motor2=motor2, start2=start2, end2=end2, points2=points2,
            dwell_time=dwell_time)


@ECLIExport
def dmesh(motor1='', start1=0.0, end1=0.0, points1=0,
          motor2='', start2=0.0, end2=0.0, points2=0,
          dwell_time=0.0):
    # Convenience function
    return scan_2d(relative=True,
            motor1=motor1, start1=start1, end1=end1, points1=points1,
            motor2=motor2, start2=start2, end2=end2, points2=points2,
            dwell_time=dwell_time)


mesh = amesh
amesh.__doc__ = _amesh.__doc__
dmesh.__doc__ = _dmesh.__doc__
