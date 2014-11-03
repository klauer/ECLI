# vi:sw=4 ts=4
"""
:mod:`ecli_splot` -- ECLI splot
===============================

.. module:: ecli_splot
   :synopsis: Simple plots for 1D/2D scans
              NOTE: This is mainly for reference, I would not recommend
                    using it. Needs major reworking.

.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""

# TODO
# * Since Qwt won't work for the image plots, should probably just switch to
#   matplotlib only

from __future__ import print_function
import os
import sys
import time
from datetime import datetime
import threading
import subprocess
import logging
import signal
import xmlrpclib
from math import sqrt

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import get_plugin
from ecli_util.decorators import ECLIExport

info_service = 0

import pyspecfile

import numpy as np
import PyQt4.Qwt5 as Qwt
import matplotlib as mpl
from PyQt4 import QtGui, QtCore
from PyQt4.QtCore import Qt, QObject
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D

import splot_util
import ecli_stepscan

PLOT_SCRIPT = os.path.join(util.ECLI_PATH, __file__)
CMAP_PREVIEW_PATH = os.path.join(os.path.dirname(__file__), '.cmap_previews')
SETTINGS_PRODUCT = 'ECLI-scan_plot'
LABEL_COUNT = 25
DATE_FORMAT = '%y-%m-%d %I:%M:%S %p'
logger = logging.getLogger('ECLI.splot')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIsplot, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIsplot)


def call_later(delay, function):
    """
    One-shot timer that calls 'function' after 'delay' ms
    """
    QtCore.QTimer.singleShot(delay, function)


class PlotError(Exception):
    pass


class PipeClosedError(PlotError):
    pass


class ECLIsplot(ECLIPlugin):
    """
    Simple plotting extension
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1),
                ('ECLIxmlrpc', 1),
                ('ECLIScanWriterSPEC', 1)
                ]

    _callbacks = []

    log_file = traitlets.Unicode(u'splot_log.txt', config=True)

    def __init__(self, shell, config):
        super(ECLIsplot, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIsplot')
        self.processes = []

    @property
    def logger(self):
        return logger

    @property
    def spec_filename(self):
        return get_plugin('ECLIScanWriterSPEC').filename

    @property
    def xmlrpc_url(self):
        xmlrpc_plugin = get_plugin('ECLIxmlrpc')
        return xmlrpc_plugin.server_url

    @ECLIExport
    def plot(self, *other_args):
        """
        Start a plot process
        """

        try:
            proc = PlotProcess(self.spec_filename,
                               '--url=%s' % self.xmlrpc_url,
                               '--output=%s' % self.log_file,
                               )
        except Exception as ex:
            print("Failed to spawn splot process (%s) %s" %
                  (ex.__class__.__name__, ex))
        else:
            self.processes.append(proc)

    def exit(self):
        for process in self.processes:
            if hasattr(process, 'join'):
                print('Waiting for plot to close...')
                process.join()
            #elif hasattr(process, 'kill'):
            #    process.kill()
            #else:
            #    self.splot_process.wait()


class PlotProcess(object):
    """
    Executes an additional process to handle plotting.
    """

    def __init__(self, *args):
        self._process = None
        self._thread = None
        self._args = list(args)
        self.run_process()

    @property
    def pid(self):
        if not self._process:
            return -1
        else:
            return self._process.pid

    def run_process(self):
        """
        Run the plot process in a thread and execute a callback when it ends
        (or crashes, of course!)
        """
        if self._thread:
            self.kill()

        kwargs = dict(on_exit=self._process_exited,
                      script=PLOT_SCRIPT)

        self._thread = threading.Thread(target=self._run_thread, kwargs=kwargs)
        self._thread.daemon = True
        self._thread.start()
        self.running = True

    def _process_exited(self, return_value):
        if return_value != 0:
            print('Plot closed: ret=%d' % return_value)
        else:
            print('Plot closed.')

        self._process = None
        self.running = False

    def kill(self):
        self.running = False
        if self._process:
            if self._process.poll() is None:  # still running
                print('Killing plot...')
                self._process.kill()
            self._process = None

        if self._thread:
            self._thread.join(0.02)
            self._thread = None

    def _run_thread(self, on_exit=None, script=None):
        """
        Start the script and run the callback on_exit if specified.
        """
        try:
            # Use the current interpreter to run the plot script
            # -u makes stdin/etc binary and unbuffered
            to_run = [sys.executable, '-u', script]
            to_run.extend(self._args)
            self._process = subprocess.Popen(to_run)
        except:
            logger.error('Spawn plot', exc_info=True)
            self._process = None
            return

        ret = self._process.wait()
        if on_exit is not None:
            on_exit(ret)


curve_symbol = Qwt.QwtSymbol(Qwt.QwtSymbol.Ellipse,
                             QtGui.QBrush(Qt.white),
                             QtGui.QPen(Qt.black, 2),
                             QtCore.QSize(7, 7))


class Curve1D(Qwt.QwtPlotCurve):
    def __init__(self, title):
        Qwt.QwtPlotCurve.__init__(self, title)
        self.setStyle(Qwt.QwtPlotCurve.Lines)
        self.setRenderHint(Qwt.QwtPlotItem.RenderAntialiased)
        self.setSymbol(curve_symbol)

    def set_color(self, color, width=2):
        pen = QtGui.QPen(color)
        pen.setWidthF(width)
        self.setPen(pen)
        self.setStyle(Qwt.QwtPlotCurve.Lines)


class TimestampScaleDraw(Qwt.QwtScaleDraw):
    def __init__(self):
        Qwt.QwtScaleDraw.__init__(self)

    def label(self, value):
        formatted = time.strftime('%H:%M:%S', time.localtime(value))
        return Qwt.QwtText(formatted)


class PlotDataSet(object):
    """
    A simple, single data set (for up to 2D data).
    """
    def __init__(self, command, names, dimensions, number=0, start_time=0):
        self.start_time = start_time
        self.acquiring = False
        self.command = splot_util.fix_scan_command(command)
        self._base_names = list(names)
        self.dimensions = list(dimensions)
        self.dimension = len(dimensions)
        if ' ' in command:
            self.scan_command = command.split(' ', 1)[0]
        else:
            self.scan_command = command

        # The 'scalar' data -- from the EPICS scalar PVs (used mostly in 1d plots)
        self.data = dict((name, np.zeros(0)) for name in names)

        # The timestamps from the scalar points:
        self.timestamps = []

        self.last_grid_point = [0] * (len(dimensions) - 1)
        self.last_point = 0
        self.scan_number = number

        # The motors that are being scanned
        self.scanning = [''] * self.dimension  # TODO

        # The timestamps of when the last calculations (evaluations) were run,
        # per evaluation string.
        self.calc_timestamps = {}
        self.visualizing = False

        # Calculation entries to remove before loading
        self.to_remove = []

        try:
            # Try to determine the wait time from the command
            info = splot_util.parse_scan_command(command)
        except ValueError:
            self.wait_time = 1.0
        else:
            self.wait_time = info['time']

    def __str__(self):
        props = ('command', 'names', 'dimensions', 'timestamps', )
        info = [(prop, str(getattr(self, prop))) for prop in props]
        return '\n'.join(['%s: \t%s' % line for line in info])

    def __getitem__(self, name):
        return self.data_by_name(name)

    def data_by_name(self, name):
        """
        Given a pv name, return the associated value lists (np.array)
        """
        if isinstance(name, (list, tuple)):
            return [self.data_by_name(n) for n in name]

        return self.data.get(name, np.zeros(0))

    def add_entry(self, name, data):
        """
        Add a new pv/data combination to the data set (appends at the end)
        """
        if name in self._base_names:
            return None

        self.names.append(name)
        self.data[name] = data

        self._update_gui()

    @property
    def names(self):
        return list(self.data.keys())

    def _update_gui(self):
        """
        """
        # TODO: don't like this -- make it a callback or something

        # Update the GUI also -- the axis selector list
        scan_widget = ScanWidget.instance
        axis_selector = scan_widget.axis_selector
        axis_selector.detectors = self.names

    def remove_entry(self, name):
        if name not in self.names or name in self._base_names:
            return

        del self.data[name]
        self._update_gui()

    def replace_entry(self, name, data):
        """
        Replace a pv/data combination in the data set -- must be the right size
        """
        if name not in self.names:
            self.add_entry(name, data)
            return

        self.data[name] = data

    def run_full_calculations(self, calc, force=True):
        message_widget = CalculationList.instance.message_widget
        updated = calc.run_on_data_set(self, force=force, message_widget=message_widget)
        if updated is None:
            return

        for name, data in updated.items():
            if data is None:
                if name in self.names:
                    self.remove_entry(name)
            elif isinstance(data, bool) and data:
                continue
            else:
                self.replace_entry(name, data)

    def save(self, filename, delimiter='\t', write_columns=True,
             write_header=True, comment_char='#'):

        print('Saving scan %s to "%s"...' % (self.scan_number, filename))

        with open(filename, 'wt') as f:
            if write_header:
                print('%s %s  %s' % (comment_char, self.scan_number, self.command), file=f)
                dimension_string = 'x'.join((str(i) for i in self.dimensions))
                print('%s %s point scan' % (comment_char, dimension_string), file=f)

            names = self.names
            if write_columns:
                print(delimiter.join(names), file=f)

            data = []
            for column in names:
                data.append(self.data[column][:self.last_point + 1])

            data = np.transpose(data)

            for line in data:
                line = delimiter.join([str(value) for value in line])
                print(line, file=f)


class DataCalculations(object):
    def __init__(self):
        self._entries = {}
        self._globals = self.build_globals()

    def build_globals(self, allowed_modules=['numpy', 'math', '__builtins__']):
        return dict((module, globals()[module]) for module in allowed_modules
                    if module in globals())

    def rename(self, name, new_name):
        if name == new_name:
            return
        elif new_name in self._entries:
            raise ValueError('Duplicate name')

        self._entries[new_name] = self._entries[name]
        del self._entries[name]

        self.update(new_name)

    def update(self, name, eval_=None):
        if eval_ not in self._entries:
            self._entries[name] = {}

        self._entries[name]['timestamp'] = time.time()
        if eval_ is not None:
            self._entries[name]['eval'] = eval_

    add = update

    def remove(self, name):
        if name in self._entries:
            del self._entries[name]

    def _run_entry_on_data_set(self, data_set, eval_str, timestamp_,
                               force=False, name='', message_widget=None):
        """
        Run one calculation on the data set
        """
        # If the calculation string has been evaluated recently (after
        # it was first modified), then it's not necessary to update it.
        data_timestamps = data_set.calc_timestamps
        if eval_str in data_timestamps and not force:
            if data_timestamps[eval_str] is None:
                # None is an indicator that this evaluation string errored.
                # Do not re-evaluate it.
                return
            elif data_timestamps[eval_str] > timestamp_:
                # Stored values are still OK
                return True

        try:
            ret = self.do_calculation(data_set, eval_str)
        except Exception as ex:
            data_timestamps[eval_str] = None
            if message_widget is not None:
                message_widget.append('%s: %s' % (name, ex))

            # print('Evaluation failed: %s' % ex)
            return None
        else:
            data_timestamps[eval_str] = time.time()
            return ret

    def run_on_data_set(self, data_set, force=False,
                        message_widget=None):
        """
        Run the set of calculations on a specific data set.
        """
        ret = {}
        if message_widget:
            message_widget.setText('%s (%s)' % (data_set.scan_number, data_set.command))

        for name, item in self._entries.items():
            ret[name] = self._run_entry_on_data_set(data_set, item['eval'],
                                                    item['timestamp'],
                                                    force=force, name=name,
                                                    message_widget=message_widget)

        return ret

    def do_calculation(self, data_set, eval_string):
        """
        An eval_string of 'pv1 + pv2' returns a new array with the sum
        of each of the elements of pv1 and pv2 in data_set.
        """
        data = data_set.data

        try:
            return eval(eval_string, self._globals, data)
        except Exception as ex:
            message = 'Evaluation failed for "%s" (%s) %s' \
                      % (eval_string, ex.__class__.__name__, ex)

            # TODO might need to disable this:
            logger.error('eval %s' % message, exc_info=True)
            raise Exception(message)


class SpecPlotDataSet(PlotDataSet):
    """
    A PlotDataSet that is loaded from one scan of a spec file
    """
    def __init__(self, sd, base_epoch=0, start_time=0):
        """
        sd = specfile.Specfile(fn)[i] -> specfile.scandata
        """
        self.command = command = splot_util.fix_scan_command(sd['command'])
        command = command.replace('  ', ' ')
        command_info = command.split(' ')
        if command_info:
            self.scan_command = command_info[0]
            if command_info[0] in ('ascan', 'dscan', 'a2scan', 'd2scan', 'repascan', 'repdscan'):
                # 0     1     2     3   4      5
                # ascan motor start end points time
                dimension_idx = [4]
                scanning_idx = [1]
            elif command_info[0] in ('amesh', 'dmesh', 'mesh'):
                # 0    1     2     3   4      5     6     7   8      9
                # mesh motor start end points motor start end points time
                dimension_idx = [4, 8]
                scanning_idx = [1, 5]
            elif command_info[0] in ('spiral', ):
                # 0        1    2      3      4   5     6     7          8
                # spiral   m1  m2 xrange yrange  dr   nth  time accumulate
                dimension_idx = None
                scanning_idx = [1, 2]
                args = [float(arg) for arg in command_info[3:7]]
                x_points, y_points = ecli_stepscan.spiral_simple(*args)

                try:
                    accumulate = int(command_info[8])
                except:
                    pass
                else:
                    x_points = np.repeat(x_points, accumulate)
                    y_points = np.repeat(y_points, accumulate)

                dimensions = [len(x_points)]

            elif command_info[0] in ('fermat', ):
                # 0        1    2      3       4   5      6     7          8
                # fermat   m1  m2 xwidth yheight  dr factor  time accumulate
                dimension_idx = None
                scanning_idx = [1, 2]

                args = [float(arg) for arg in command_info[3:7]]
                x_points, y_points = ecli_stepscan.spiral_fermat(*args)
                try:
                    accumulate = int(command_info[8])
                except:
                    pass
                else:
                    x_points = np.repeat(x_points, accumulate)
                    y_points = np.repeat(y_points, accumulate)

                dimensions = [len(x_points)]

            elif command_info[0] in ('timescan', ):
                # 0         1      2
                # timescan  count  sleep
                dimension_idx = None
                scanning_idx = []
                dimensions = [len(sd['lines'])]
            else:
                raise ValueError(command_info[0])

            try:
                ## dimensions are 0-based in spec files
                #dimensions = [int(command_info[idx]) + 1 for idx in dimension_idx]
                if dimension_idx is not None:
                    dimensions = [int(command_info[idx]) for idx in dimension_idx]
            except:
                dimensions = [0] * len(dimension_idx)

            scanning = [command_info[idx] for idx in scanning_idx]

        PlotDataSet.__init__(self, command, sd['columns'], dimensions, number=sd['number'],
                             start_time=start_time)

        line_lengths = set(len(line) for line in sd['lines'])
        if len(line_lengths) > 1:
            print('Bad scan: (%s) %s' % (sd['number'], sd['command']))
            return

        try:
            lines = np.array(sd['lines'])
        except Exception as ex:
            print('->', ex, sd['lines'])
            raise

        data = dict((name, lines[:, i]) for i, name in enumerate(sd['columns']))
        self.data = data

        if 'Epoch' in self.names:
            self.timestamps = self.data['Epoch'] + base_epoch
        else:
            self.timestamps = []

        self.dimension = len(dimensions)
        self.dimensions = dimensions
        self.scanning = scanning

        total_pixels = 1
        for dim in dimensions:
            total_pixels *= dim

        self.last_point = len(lines)
        if total_pixels == len(lines):
            self.last_grid_point = dimensions
        else:
            dimensions_valid = [(dim > 0) for dim in dimensions]
            if False not in dimensions_valid:
                self.last_grid_point = ecli_stepscan.get_grid_point(dimensions, len(lines))
#SpecPlotDataSet = PySpecPlotDataSet


class PlotData(object):
    """
    Holds PlotDataSets.

    Polls ECLI and adds new PlotDataSets when necessary.
    """
    def __init__(self, parent):
        self.clear()
        self._calculations = CalculationList.instance.calculations
        self._plots = [parent.plot_1d, parent.plot_2d]

        self._url = None
        self._update_available = True

        self._scan_info = None
        self._scan_number = None
        self.client = None

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.check_updates)
        self.timer.start(1000)

    def clear(self):
        self.data_sets = []
        self._current = None
        self._acquiring = None
        self._last_number = None
        self._spec_filename = None

    def __iter__(self):
        for set_ in self.data_sets:
            yield set_

    def _get_current_data_set(self):
        return self._current

    def _set_current_data_set(self, data_set):
        self._current = data_set

    current_data_set = property(_get_current_data_set, _set_current_data_set)

    def remove_from_all(self, name):
        """
        Add to the list of entries to remove before loading the data set.
        """
        for set_ in self.data_sets:
            set_.to_remove.append(name)

    @property
    def acquiring_data_set(self):
        return self._acquiring

    @property
    def acquiring_visible(self):
        """
        Whether or not the currently acquired scan is being plotted
        """
        return (self._current == self._acquiring or self._current is None or
                self._current == self.data_sets[-1])

    def _get_url(self):
        return self._url

    def _set_url(self, url):
        if url != self._url and url:
            if url is None:
                self.client = None
            else:
                self.client = xmlrpclib.ServerProxy(url)
            self._url = url

    url = property(_get_url, _set_url, doc='XMLRPC server URL')

    @property
    def update_available(self):
        if not self._update_available:
            newest_key = self.client.get_scan_key()
            self._update_available = (newest_key != self._scan_key)
            return self._update_available
        else:
            return True

    def _update_info(self):
        if self.client is None or not self.update_available:
            return False

        self._scan_info = info = self.client.get_scan_info()
        if 'key' not in info:
            return False

        self._scan_key = info['key']
        self._update_available = False
        return True

    def check_updates(self):
        if not self._update_info():
            return

        info = self._scan_info

        number = info['scan_number']
        new_scan = (number != self._last_number)
        self._last_number = number

        #for key, value in info.items():
        #    print('\t%s:\t%s' % (key, value))

        if new_scan:
            self.scan_started()
        elif not info['done']:
            pass

        self._grab_server_data()

        if self.acquiring_visible:
            data_set = self._acquiring
            self._acquiring.acquiring = True

            calc_list = CalculationList.instance
            calculations = calc_list.calculations
            data_set.run_full_calculations(calculations)

            for plot in self._plots:
                plot.data_updated()

        if info['done']:
            self.scan_finished()

    def _grab_server_data(self):
        data_set = self._acquiring
        if data_set:
            data = np.array(self.client.get_scan_data())
            data_set.data = dict((name, data[:, i]) for i, name in enumerate(data_set._base_names))

            #print(data_set)

            info = self._scan_info
            data_set.last_point = info['point']
            data_set.last_grid_point = ecli_stepscan.get_grid_point(info['dimensions'],
                                                                    info['point'] - 1)
            data_set.timestamps = info.get('timestamps', [])
            if data_set.timestamps and 'Epoch' not in data_set.data:
                ts = np.array(data_set.timestamps)
                data_set.data['Epoch'] = ts - ts[0]

    def _add_data_set(self, data_set):
        self.data_sets.append(data_set)

        # TODO also as a callback to make this more independent
        #if isinstance(data_set, SpecPlotDataSet):
        #    return data_set

        try:
            calculation_list = CalculationList.instance
        except:
            pass
        else:
            calculation_list.data_set_added(data_set)

        return data_set

    def scan_started(self):
        """
        A new scan has started
        """
        info = self._scan_info
        title = info['title']

        print('--> (plot) New scan started: %s' % (title, ))
        # print(info)

        try:
            start_time = info['timestamps'][0]
        except:
            start_time = time.time()

        data_set = PlotDataSet(info['command'], info['labels'],
                               info['dimensions'], number=self._last_number,
                               start_time=start_time,
                               )

        data_set.scanning = info['scanning']

        self._add_data_set(data_set)
        self._acquiring = data_set

        scan_list = get_scan_list()
        scan_list.add_scan(data_set, select_plot=True)

        #if self._current is None:
        self._current = self._acquiring

        calc_list = CalculationList.instance

        for plot in self._plots:
            plot.scan_started(True, data_set)
        calc_list.disable_modifications()

        scan_list.selection_changed()

    def scan_finished(self):
        print('--> (plot) Scan finished')
        calc_list = CalculationList.instance
        calc_list.enable_modifications()

        # data_set = self._acquiring
        if self._acquiring is not None:
            self._acquiring.acquiring = False
            self._acquiring = None

    def load_spec_file(self, fn):
        """
        Loads a SPEC-format file into the PlotData, creating a SpecPlotDataSet
        (a subclass of PlotDataSet) for each scan in the file.
        """
        print('Loading spec file: %s' % fn)
        if not os.path.exists(fn):
            print('(Spec file does not exist: %s)' % fn)
            return

        self._spec_filename = fn

        if os.path.getsize(fn) == 0:
            print('(Empty SPEC file)')
            return

        try:
            sf = pyspecfile.SPECFileReader(fn)
        except Exception as ex:
            print('ERROR: Unable to load spec file: %s (%s)' % (fn, ex))
            return

        self.clear()
        self._spec_filename = fn

        base_epoch = sf.epoch()

        for scan in sf.scans:
            try:
                start_time = scan['time']
                pds = SpecPlotDataSet(scan, base_epoch=base_epoch, start_time=scan['time'])
            except Exception as ex:
                print('specfile ERROR: Failed to load scan #%s (%s, %s): %s: %s' %
                      (scan['number'], scan['command'], start_time, ex.__class__.__name__, ex),
                      file=sys.stderr)
                raise
            else:
                self._add_data_set(pds)


class Plot1D(Qwt.QwtPlot):
    """
    1D Plotting with Qwt
    """

    colors_for_dark_bg = [Qt.green, Qt.white, Qt.red, Qt.darkGreen, Qt.blue, Qt.darkBlue,
                          Qt.cyan, Qt.darkCyan, Qt.magenta, Qt.darkMagenta, Qt.yellow, Qt.darkYellow,
                          ]

    colors_for_light_bg = [Qt.green, Qt.red, Qt.black, Qt.darkRed, Qt.darkGreen, Qt.blue, Qt.darkBlue,
                           Qt.cyan, Qt.darkCyan, Qt.magenta, Qt.darkMagenta, Qt.yellow, Qt.darkYellow,
                           ]

    def __init__(self, parent=None):
        Qwt.QwtPlot.__init__(self, parent)

        self.setCanvasBackground(Qt.white)

        self.label_font = self.font()
        self.label_font.setPixelSize(self.label_font.pixelSize() / 2)

        self.small_font = self.font()
        self.small_font.setPixelSize(8)

        self.title_font = self.font()
        self.title_font.setPixelSize(14)

        legend = self._legend = Qwt.QwtLegend()
        legend.setItemMode(Qwt.QwtLegend.CheckableItem)
        self.insertLegend(legend, Qwt.QwtPlot.ExternalLegend)

        zoomer = self.zoomer = Qwt.QwtPlotZoomer(self.canvas())
        zoomer.setRubberBandPen(QtGui.QColor(Qt.red))
        zoomer.setTrackerPen(QtGui.QColor(Qt.red))
        zoomer.setMousePattern(Qwt.QwtEventPattern.MouseSelect2, Qt.MidButton, Qt.ControlModifier)
        zoomer.setMousePattern(Qwt.QwtEventPattern.MouseSelect3, Qt.MidButton)

        self.tracker = Qwt.QwtPlotPicker(Qwt.QwtPlot.xBottom, Qwt.QwtPlot.yLeft,
                                         Qwt.QwtPicker.PointSelection,
                                         Qwt.QwtPlotPicker.CrossRubberBand,
                                         Qwt.QwtPicker.AlwaysOn,
                                         self.canvas())

        panner = self.panner = Qwt.QwtPlotPanner(self.canvas())
        panner.setMouseButton(Qt.RightButton)

        magnifier = self.magnifier = Qwt.QwtPlotMagnifier(self.canvas())
        magnifier.setMouseButton(Qt.NoButton)

        QObject.connect(self, QtCore.SIGNAL("legendChecked(QwtPlotItem*, bool)"), self.legend_checked)
        QObject.connect(zoomer, QtCore.SIGNAL("zoomed(const QRectF)"), self.zoomed)

        self.colors = self.colors_for_light_bg
        self.curves = {}
        self.names = []
        self._data = None
        self._mode = None
        self._x_axis = None

    def create_options(self):
        # TODO 1D display options -- like logarithmic scaling etc
        self.options = QtGui.QFrame()
        return self.options, []

    def use_time_scale(self, spacing=10, rotation=-30.0):
        """
        Use timestamps on the x-axis
        """
        time_scale = TimestampScaleDraw()
        time_scale.setSpacing(spacing)
        self.setAxisScaleDraw(Qwt.QwtPlot.xBottom, time_scale)
        self.setAxisLabelRotation(Qwt.QwtPlot.xBottom, rotation)
        self.set_x_title('Time')
        self._x_axis = None

    def use_point_scale(self, x_axis=None, label=None, spacing=10):
        """
        Use points on the x-axis
        """
        if label is None:
            label = 'Data point'

        if x_axis is None:
            x_axis = self._x_axis

        point_scale = Qwt.QwtScaleDraw()
        point_scale.setSpacing(spacing)
        self.setAxisScaleDraw(Qwt.QwtPlot.xBottom, point_scale)
        self.set_x_title(label)
        self._x_axis = x_axis

    def set_x_title(self, title):
        self._x_title = title
        if self._data is not None:
            data_set = self._data
            ts0 = datetime.fromtimestamp(data_set.start_time)
            spec_filename = PlotWindow.instance.data._spec_filename
            if spec_filename is None:
                spec_filename = ''
            else:
                spec_filename = '%s ' % (os.path.split(spec_filename)[-1])
            title = '%s\n%s%s' % (title, spec_filename, ts0.strftime(DATE_FORMAT))

        t = Qwt.QwtText(title)
        t.setFont(self.label_font)
        self.setAxisTitle(Qwt.QwtPlot.xBottom, t)

    def auto_scale(self):
        """
        Auto scale the plot
        """
        self.setAxisAutoScale(Qwt.QwtPlot.yLeft)
        self.setAxisAutoScale(Qwt.QwtPlot.xBottom)
        self.zoomer.setZoomBase(False)

    def zoomed(self, *args):
        """
        A callback indicating the user zoomed the plot.
        """
        if self.zoomer.zoomRectIndex() == 0:
            self.auto_scale()

        self.replot()

    def show_only(self, names):
        """
        Show only the curves corresponding to the list of names
        """
        for name, curve in self.curves.items():
            self.set_visibility(curve, (name in names), replot=False)

        self.auto_scale()
        self.replot()

    def set_visibility(self, plot_item, visible, name=None, replot=True):
        """
        Set the visibility of a single plot item.
        """
        if plot_item is None and name is None:
            return
        elif name and name not in self.names:
            return

        if plot_item is None:
            plot_item = self.curves[name]

        plot_item.setVisible(visible)
        plot_item.setItemAttribute(Qwt.QwtPlotItem.AutoScale, visible)

        widget = self.legend().find(plot_item)
        if widget and isinstance(widget, Qwt.QwtLegendItem):
            widget.setChecked(visible)

        if replot:
            self.replot()

    legend_checked = set_visibility

    # 1D
    def scan_started(self, new_scan, data_set, axis_sel=None, x_axis=None, x_title=None):
        """
        A notification from PlotData that a scan has started
        """
        self._data = data_set
        title = '#%s  %s' % (data_set.scan_number, data_set.command)

        names = data_set.names

        qwt_title = Qwt.QwtText(title)
        qwt_title.setFont(self.title_font)
        self.setTitle(qwt_title)

        if new_scan and self.names != names:
            for curve in self.curves.values():
                curve.detach()
            self.curves = dict((name, Curve1D(name)) for name in names)

        axis_sel = AxisSelector.instance
        for i, (name, curve) in enumerate(self.curves.items()):
            color = self.colors[i % len(self.colors)]

            curve.attach(self)
            curve.set_color(color)
            axis_item = axis_sel.item(i, 0)
            if axis_item is not None:
                if color in (Qt.black, Qt.darkBlue, Qt.blue):
                    axis_item.setForeground(Qt.gray)

                axis_item.setBackground(color)

            legend_item = self.legend().find(curve)
            if legend_item is not None:
                legend_item.setChecked(name in axis_sel.checked_y_names)

        if x_axis is None:
            x_axis = range(1, data_set.dimensions[-1] + 1)
        else:
            x_axis = list(x_axis)

        self.auto_scale()
        self.replot()

    def data_updated(self):
        """
        A notification from PlotData that a new data has arrived
        (or at least should be plotted)
        """
        if not self._data or not self.curves:
            return

        if not self._data.data:
            print('* new_data: data unset (?)')
            return

        axis_selector = AxisSelector.instance
        x_names = axis_selector.checked_x_names

        data_set = self._data
        if not x_names or x_names[0] not in data_set.data:
            points = data_set.dimensions[-1]
            if data_set.timestamps is not None and len(data_set.timestamps) >= points:
                x_axis = data_set.timestamps
                self.use_time_scale()
            else:
                x_axis = range(1, points + 1)
                self.use_point_scale(x_axis, label='Data point')
        else:
            name = x_names[0]
            x_axis = data_set.data[name]
            if name == 'Epoch':
                x_axis = x_axis - x_axis[0]
                name = 'Elapsed time'

            self.use_point_scale(x_axis, label=name)

        for name, curve in self.curves.items():
            data = self._data[name][:self._data.last_point + 1]
            if data is not None:
                curve.setData(x_axis, data)

        self.auto_scale()
        self.replot()

    def _get_mode(self):
        return self._mode

    def _set_mode(self, mode):
        raise ValueError('Unknown 1d plotting mode')


class ScanList(QtGui.QTreeWidget):
    LABELS = ['Scan #', 'Command', 'Points']
    HEADER_SIZE = [QtGui.QHeaderView.ResizeToContents,
                   QtGui.QHeaderView.Interactive,
                   QtGui.QHeaderView.ResizeToContents]

    def __init__(self, parent=None):
        QtGui.QTreeWidget.__init__(self, parent)

        ScanList.instance = self
        self.setSortingEnabled(False)
        # if multiple scans are selectable: (not implemented yet)
        # self.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)

        # Setup the header
        self.setColumnCount(len(ScanList.LABELS))
        self.setHeaderLabels(ScanList.LABELS)

        for i, size in enumerate(ScanList.HEADER_SIZE):
            self.header().setResizeMode(i, size)

        # And setup some slots
        self.connect(self, QtCore.SIGNAL('itemSelectionChanged()'),
                     self.selection_changed)

    def selection_changed(self):
        selected_indices = [self.indexOfTopLevelItem(item)
                            for item in self.selectedItems()]

        scan_widget = ScanWidget.instance
        scan_widget.scans_selected(selected_indices)

    def add_scan(self, data, select_plot=False):
        dimension_string = 'x'.join((str(i) for i in data.dimensions))
        item_data = [str(data.scan_number), str(data.command), dimension_string]
        item = QtGui.QTreeWidgetItem(item_data)

        self.addTopLevelItem(item)
        if select_plot:
            #print('selecting plot')
            for _item in self.selectedItems():
                _item.setSelected(False)

            item.setSelected(True)

            self.selection_changed()

        return item


class AxisSelector(QtGui.QTableWidget):
    LABELS = ['Detector', 'X', 'Y', 'Z']

    def __init__(self, parent=None):
        QtGui.QTableWidget.__init__(self, parent)

        AxisSelector.instance = self

        # Setup the header
        self.setColumnCount(len(AxisSelector.LABELS))
        self.setHorizontalHeaderLabels(AxisSelector.LABELS)

        self._detectors = []
        self._loading = False
        self.data_set = None
        self.default_foreground = Qt.black
        self.default_background = Qt.white

    def set_data(self, data):
        old_data_set = self.data_set

        self.data_set = data

        if data is not None:
            self._loading = True
            names = list(data.names)
            scan_names = []
            for scanning in data.scanning:
                if scanning in names:
                    scan_names.append(scanning)
                    names.remove(scanning)

            try:
                self.detectors = scan_names + names
            except:
                raise
            finally:
                self._loading = False
                data.visualizing = True

                if old_data_set:
                    old_data_set.visualizing = False

    def clear_colors(self):
        if self.rowCount() > 0:
            #background = self.item(0, 1).background()
            background = self.default_background
            foreground = self.default_foreground
            for i in range(self.rowCount()):
                item = self.item(i, 0)
                item.setBackground(background)
                item.setForeground(foreground)

    def _get_detectors(self):
        return list(self._detectors)

    def _set_detectors(self, detectors):
        if set(detectors) == set(self._detectors):
            return

        old_selections = self.all_checked_names

        self._detectors = list(detectors)

        self.setRowCount(len(detectors))
        for i, det in enumerate(detectors):
            # Set the label (create or re-use if it already exists)
            item = self.item(i, 0)
            if item is None:
                item = QtGui.QTableWidgetItem(det)
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.setItem(i, 0, item)
            else:
                item.setText(det)

            for j, label in enumerate(AxisSelector.LABELS):
                if j == 0:
                    continue

                checkbox = self.item(i, j)
                if checkbox is None:
                    checkbox = QtGui.QCheckBox()
                    self.connect(checkbox, QtCore.SIGNAL('clicked(bool)'),
                                 lambda checked, det=det, type_=label:
                                 self.checkbox_toggled(det, type_, checked))
                    self.setCellWidget(i, j, checkbox)

        for label, checked in zip(AxisSelector.LABELS[1:], old_selections):
            self.check_names(label, checked)

        self.resizeColumnsToContents()

    detectors = property(_get_detectors, _set_detectors,
                         doc='The list of detectors')

    @property
    def all_checked_names(self):
        return [self.checked_names(x) for x in AxisSelector.LABELS[1:]]

    @property
    def all_checked_indices(self):
        return [self.checked_indices(x) for x in AxisSelector.LABELS[1:]]

    def checkbox_toggled(self, det, type_, checked):
        if self._loading:
            return

        ScanWidget.instance.axes_selected(*self.all_checked_names, event=(det, type_, checked))

    def _get_column(self, column_name='X'):
        """
        Get the full column of widgets (checkboxes) or strings (detectors)
        """
        column = AxisSelector.LABELS.index(column_name)
        if column == 0:
            return self._detectors
        elif column > 0:
            return [self.cellWidget(i, column) for i in range(self.rowCount())]

    def check_names(self, label, names, max_=None):
        """
        For a specific column label, check the checkboxes indicated in the list
        of names.
        NOTE: Will not trigger individual callbacks.
        """
        self._loading = True

        try:
            widgets = dict((detector, widget) for (detector, widget)
                           in zip(self._detectors, self._get_column(label)))

            checked = set(self._detectors).intersection(set(names))
            unchecked = set(self._detectors) - checked

            if max_ is not None:
                if len(checked) > max_:
                    checked = list(sorted(checked, key=lambda s: names.index(s)))[:max_]

            for name in checked:
                widgets[name].setChecked(True)

            for name in unchecked:
                widgets[name].setChecked(False)

        finally:
            self._loading = False

    def checked_names(self, label='X'):
        """
        For a specific column, for each checked checkbox,
        return all detector names.
        """
        return [detector for detector, widget
                in zip(self._detectors, self._get_column(label))
                if widget.isChecked()]

    @property
    def checked_x_names(self):
        return self.checked_names('X')

    @property
    def checked_y_names(self):
        return self.checked_names('Y')

    @property
    def checked_z_names(self):
        return self.checked_names('Z')

    def check_indices(self, label, indices):
        """
        For a specific column label, check the checkboxes indicated in the list
        of indices.
        NOTE: Will not trigger individual callbacks.
        """
        self._loading = True
        try:
            for i, widget in enumerate(self._get_column(label)):
                widget.setChecked(i in indices)
        finally:
            self._loading = False

    def checked_indices(self, label='X'):
        """
        For a specific column, for each checked checkbox,
        return all detector indices.
        """
        return [i for i, (detector, widget)
                in enumerate(zip(self._detectors, self._get_column(label)))
                if widget.isChecked()]

    @property
    def checked_x_indices(self):
        return self.checked_indices('X')

    @property
    def checked_y_indices(self):
        return self.checked_indices('Y')

    @property
    def checked_z_indices(self):
        return self.checked_indices('Z')


class ScanWidget(QtGui.QSplitter):
    """
    A splitter which holds the list of scans on top and the axis selector on bottom.
    """
    def __init__(self, parent=None):
        QtGui.QSplitter.__init__(self, parent)

        ScanWidget.instance = self

        self.setOrientation(Qt.Vertical)

        # the list on top, with the scans
        self.scan_list = ScanList()

        # and the table on the bottom, with the detectors, and x/y/z, etc.
        self.axis_selector = AxisSelector()

        self.addWidget(self.scan_list)
        self.addWidget(self.axis_selector)
        self.data = None
        self._loading = False

    def reload_data(self):
        if self.data is None:
            return

        self.scan_list.clear()
        for data in self.data:
            self.scan_list.add_scan(data)

    def scans_selected(self, selected_indices):
        if not selected_indices:
            return

        index = selected_indices[0]
        print('Scan selected %d' % index)
        self.data.current_data_set = data = list(self.data)[index]
        self.axis_selector.set_data(data)

        for to_remove in data.to_remove:
            data.remove_entry(to_remove)

        data.to_remove = []

        calc_list = CalculationList.instance
        calculations = calc_list.calculations
        if self.data.acquiring_visible:
            calc_list.disable_modifications()
        else:
            calc_list.enable_modifications()
            data.run_full_calculations(calculations)

        x, y, z = self.axis_selector.all_checked_names
        if data.dimension == 2 or data.scan_command in ('spiral', 'fermat'):
            new_x, new_y = data.scanning
            new_x = splot_util.readback_pvs(new_x) + [new_x]
            new_y = splot_util.readback_pvs(new_y) + [new_y]

            self.axis_selector.check_names('X', new_x, max_=1)
            self.axis_selector.check_names('Y', new_y, max_=1)
            self.axis_selector.check_names('Z', z)  # ['sca4'])
        elif data.dimension == 1:
            if len(z) >= 1:
                self.axis_selector.check_names('Z', [])

            if data.scanning:
                new_x = data.scanning[0]
                new_x = splot_util.readback_pvs(new_x) + [new_x]

            self.axis_selector.check_names('X', new_x)

            if not self.axis_selector.checked_y_names:
                if 'xs_roi1' in data.names:
                    self.axis_selector.check_names('Y', ['xs_roi1'])
                else:
                    self.axis_selector.check_names('Y', [data.names[0]])

        self.update_axes()

    def update_axes(self):
        self.axes_selected(*self.axis_selector.all_checked_names)

    def axes_selected(self, x, y, z, event=None):
        """
        An axis checkbox was changed.
        """
        #print('axes selected', x, y, z, 'event', event)
        plot_window = PlotWindow.instance
        data = self.data.current_data_set
        scan_widget = ScanWidget.instance
        if event is None:
            # New scan
            pass
        else:
            # Clicked a single checkbox
            new_name, new_label, new_checked = event
            if new_label == 'X' and len(x) > 1:
                self.axis_selector.check_names('X', [new_name])
                return
            elif new_label == 'Z' and new_checked and len(y) > 1:
                self.axis_selector.check_names('Y', [y[0]])
                return

        if len(z) == 0:  # len(y) >= 1 and len(z) == 0:
            # 1d
            plot_window.set_dimension(1)
            plot = plot_window.plot_1d
            x_data = None
            if len(x) >= 1:
                x_name = x[0]
                try:
                    x_data = data.data[x_name]
                except:
                    x_data = None
                    print('* Scalar data x_axis fail')

                if x_name == 'Epoch':
                    x_data = x_data - x_data[0]
                    x_name = 'Elapsed time'

                plot.use_point_scale(x_data, label=x_name)

            plot.scan_started(True, data, axis_sel=scan_widget.axis_selector, x_axis=x_data)
            if not y:
                y = ['xs_roi1']
                #print('setting xs_roi1')

            plot.show_only(y)

            plot.data_updated()

        elif len(x) == 1 and len(y) == 1 and len(z) >= 1:
            # 2d
            x, y = x[0], y[0]
            scan_widget.axis_selector.clear_colors()
            plot_window.set_dimension(2)
            plot = plot_window.plot_2d
            plot._axis_names = (x, y, z)
            plot._data = data
            plot.recalculate()


class CalculationList(QtGui.QFrame):
    def __init__(self, parent=None):
        QtGui.QFrame.__init__(self, parent)

        CalculationList.instance = self
        self._loading = False

        self.layout = QtGui.QBoxLayout(QtGui.QBoxLayout.TopToBottom, parent=self)

        # The splitter separating the top and bottom
        self.splitter = QtGui.QSplitter()
        self.splitter.setOrientation(Qt.Vertical)

        self.layout.addWidget(self.splitter)

        # The table to hold calculations
        self.top_frame = QtGui.QFrame()
        self.table = QtGui.QTableWidget(1, 2)
        self.table.setHorizontalHeaderLabels(['Name', 'Formula'])
        self.table.cellChanged.connect(self.cell_changed)

        # The layout
        self.top_layout = QtGui.QGridLayout()
        self.top_frame.setLayout(self.top_layout)

        self.top_layout.addWidget(self.table, 0, 0, 1, 2)

        self.calculations = DataCalculations()

        # Add/remove push buttons
        self.add_button = QtGui.QPushButton()
        self.add_button.setText('&Add')

        self.remove_button = QtGui.QPushButton()
        self.remove_button.setText('&Remove')

        self.top_layout.addWidget(self.add_button, 1, 0)
        self.top_layout.addWidget(self.remove_button, 1, 1)

        self.add_button.clicked.connect(self.add_clicked)
        self.remove_button.clicked.connect(self.remove_clicked)

        # The bottom message window and the splitter setup
        self.message_widget = QtGui.QTextEdit()

        self.splitter.addWidget(self.top_frame)
        self.splitter.addWidget(self.message_widget)

        # Rows stored in the calculation set (row: stored_name)
        self.stored_rows = {}

    def disable_modifications(self):
        self.add_button.setEnabled(False)
        self.remove_button.setEnabled(False)

    def enable_modifications(self):
        self.add_button.setEnabled(True)
        self.remove_button.setEnabled(True)

    def data_set_added(self, data_set):
        data_set.run_full_calculations(self.calculations)

    def _entry_at_row(self, row):
        name = self.table.item(row, 0)
        if name is not None:
            name = str(name.text())
        else:
            name = ''

        value = self.table.item(row, 1)
        if value is not None:
            value = str(value.text())
        else:
            value = ''

        return name.strip(), value.strip()

    @property
    def current_entry(self):
        row = self.table.currentRow()
        name, value = self._entry_at_row(row)
        return row, name, value

    def update_current_data_set(self):
        get_scan_list().selection_changed()

    def cell_changed(self, row, col):
        if self._loading:
            return

        name, value = self._entry_at_row(row)
        if col == 0:  # name changed
            if name and value:
                if row in self.stored_rows:
                    old_name, value = self.stored_rows[row]
                    self.calculations.rename(old_name, name)
                    #print('rename %s -> %s' % (old_name, name))
                else:
                    #print('set name', name)
                    self.calculations.update(name, value)

                self.stored_rows[row] = (name, value)
                self.update_current_data_set()

        else:  # value changed
            if name != '':
                self.calculations.update(name, value)
                self.stored_rows[row] = (name, value)
                self.update_current_data_set()

    def add_clicked(self):
        """
        Add a new row to the table
        """
        self.table.insertRow(self.table.rowCount())

    def remove_clicked(self):
        """
        Delete the current row from the table
        """
        row, name, value = self.current_entry
        if row == -1:
            return

        # Remove it from the table itself
        self.table.removeRow(row)
        if row in self.stored_rows:
            name, value = self.stored_rows[row]

        # Queue it to be removed from each of the data sets
        window = PlotWindow.instance
        window.data.remove_from_all(name)

        # Remove it from the calculation list
        self.calculations.remove(name)

        # And update the corresponding stored rows with the new locations
        stored_rows = {}
        for i, (name_, value_) in self.stored_rows.items():
            if i > row:
                stored_rows[i - 1] = (name_, value_)
            elif i == row:
                pass
            elif i < row:
                stored_rows[i] = (name_, value_)

        self.stored_rows = stored_rows
        #print('Remaining:')
        #for i, (name_, value_) in self.stored_rows.items():
        #    print('\t', i, name_, value_)

        self.update_current_data_set()

    def save_list(self, settings):
        print('Saving pseudo detectors...')
        settings.beginGroup('pseudo-detector')
        settings.setValue('count', len(self.stored_rows.keys()))
        for i, (name, value) in self.stored_rows.items():
            settings.setValue('%d-name' % i, name)
            settings.setValue('%d-value' % i, value)

        settings.endGroup()

    def update_gui_from_settings(self, entries):
        self.table.setRowCount(0)
        for i, name, value in entries:
            self.table.insertRow(i)

            self.stored_rows[i] = (name, value)
            self.table.setItem(i, 0, QtGui.QTableWidgetItem(name))
            self.table.setItem(i, 1, QtGui.QTableWidgetItem(value))

    def load_list(self, settings):
        print('Loading pseudo detectors...')
        self._loading = True
        settings.beginGroup('pseudo-detector')

        count = settings.value('count', 0, type=int)
        entries = []
        for i in range(count):
            name = settings.value('%d-name' % i, defaultValue='', type=str)
            value = settings.value('%d-value' % i, defaultValue='', type=str)

            if not name or not value:
                continue

            entries.append((i, name, value))

        self._loading = False

        if entries:
            self.update_gui_from_settings(entries)

        settings.endGroup()


class PlotWindow(QtGui.QMainWindow):
    def __init__(self, **kwargs):
        QtGui.QMainWindow.__init__(self, **kwargs)
        PlotWindow.instance = self

        self.setContentsMargins(10, 10, 10, 10)

        # Set up the tabs
        self.tab_widget = QtGui.QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # The calculation list
        self.calculation_list = CalculationList()

        # Create the main splitter, holding <left widgets> | <stacked plots>
        self.main_splitter = QtGui.QSplitter()

        tabs = [(self.main_splitter, 'Plot'),
                (self.calculation_list, 'Pseudo-detectors')
                ]

        if False:
            tabs.reverse()

        for tab in tabs:
            self.tab_widget.addTab(*tab)

        # Set up the 1D plot
        self.plot_1d = Plot1D()
        self.plot_1d_options, save_widgets1 = self.plot_1d.create_options()

        splitter = self.splitter_1d = QtGui.QSplitter()
        splitter.setOrientation(Qt.Vertical)

        #splitter.addWidget(self.plot_1d.legend().contentsWidget())
        splitter.addWidget(self.plot_1d)

        # Set up the 2D plot
        self.plot_2d = Plot2D()
        Plot2D.instance = self.plot_2d

        self.plot_2d_options, save_widgets2 = self.plot_2d.create_options()

        splitter = self.splitter_2d = QtGui.QSplitter()
        splitter.addWidget(self.plot_2d)

        self.plot_widgets = [self.splitter_1d, self.splitter_2d]
        self.plots = [self.plot_1d, self.plot_2d]
        self.plot_options = [self.plot_1d_options, self.plot_2d_options]

        # Add the stack to hold each of these widgets
        self.stack = QtGui.QStackedWidget()
        for widget in self.plot_widgets:
            self.stack.addWidget(widget)

        self.scan_widget = ScanWidget()
        self.options_stack = QtGui.QStackedWidget()
        for option in self.plot_options:
            if option is not None:
                self.options_stack.addWidget(option)

        self.left_widgets = QtGui.QSplitter()
        self.left_widgets.setOrientation(Qt.Vertical)

        self.left_widgets.addWidget(self.scan_widget)
        self.left_widgets.addWidget(self.options_stack)

        # left widget is:
        # <scan widget>
        # -- splitter --
        # <options for 1d/2d plots>

        self.main_splitter.addWidget(self.left_widgets)
        self.main_splitter.addWidget(self.stack)

        # The widgets that should have their positions/etc saved
        self.position_widgets = [('main', self),
                                 ('splitter_1d', self.splitter_1d),
                                 ('splitter_2d', self.splitter_2d),
                                 ('plot_1d', self.plot_1d),
                                 ('plot_2d', self.plot_2d),
                                 ]
        self.position_widgets.extend(save_widgets1)
        self.position_widgets.extend(save_widgets2)

        self.printer = QtGui.QPrinter()

        self.create_menu()
        self._dimension = 0
        # Show a 1d plot at startup
        self.set_dimension(1)

        self.load_positions()

        self.data = PlotData(self)
        self.scan_widget.data = self.data

    def create_menu(self):
        menubar = QtGui.QMenuBar()
        file_menu = menubar.addMenu('&File')
        open_file = file_menu.addAction('&Open SPEC file...')
        save_image = file_menu.addAction('&Save image as...')
        save_data = file_menu.addAction('Save plot &data...')
        file_menu.addSeparator()
        print_ = file_menu.addAction('&Print...')
        print_small = file_menu.addAction('P&rint small...')
        file_menu.addSeparator()
        exit = file_menu.addAction('E&xit')
        self.setMenuBar(menubar)

        open_file.triggered.connect(lambda *args: self.load_spec_file())
        save_image.triggered.connect(lambda *args: self.save_image())
        save_data.triggered.connect(lambda *args: self.save_data())
        print_.triggered.connect(lambda *args: self.print_())
        print_small.triggered.connect(lambda *args: self.print_(small=True))
        exit.triggered.connect(lambda *args: self.close())

    def closeEvent(self, event):
        if self.data is not None:
            self.data.timer.stop()
        self.url = None
        self.save_positions()

    @property
    def settings(self):
        return QtCore.QSettings('BNL', SETTINGS_PRODUCT)

    def load_positions(self):
        settings = self.settings
        for name, widget in self.position_widgets:
            geometry = '%s_geometry' % name
            state = '%s_state' % name
            if settings.contains(geometry) and hasattr(widget, 'restoreGeometry'):
                widget.restoreGeometry(settings.value(geometry).toByteArray())
            if settings.contains(state) and hasattr(widget, 'restoreState'):
                widget.restoreState(settings.value(state).toByteArray())

        self.calculation_list.load_list(settings)

    def save_positions(self):
        settings = self.settings
        for name, widget in self.position_widgets:
            geometry = '%s_geometry' % name
            if hasattr(widget, 'saveGeometry'):
                settings.setValue(geometry, widget.saveGeometry())
            state = '%s_state' % name
            if hasattr(widget, 'saveState'):
                settings.setValue(state, widget.saveState())

        self.calculation_list.save_list(settings)

    def set_dimension(self, d):
        """
        Show the main plot widget for a given dimension (1, 2)
        """
        if d != self._dimension:
            self._plot_widget = self.plot_widgets[d - 1]
            self._plot = self.plots[d - 1]
            self._options = options = self.plot_options[d - 1]

            self.stack.setCurrentWidget(self._plot_widget)
            if options is not None:
                self.options_stack.setCurrentWidget(options)

            self.plots[d - 1].active = True
            self._dimension = d

    def save_data(self, filename=''):
        data_set = self.data.current_data_set
        if data_set is None:
            print('Data set not selected')
            return

        if not filename:
            filename = QtGui.QFileDialog.getSaveFileName(self, 'Save as', '', 'Text files (*.txt)')
            if not filename:
                return

        data_set.save(filename)

    def save_image(self, filename=''):
        if self._dimension == 1:
            if not filename:
                filename = QtGui.QFileDialog.getSaveFileName(self, 'Save as', '', 'PDF files (*.pdf)')
                if not filename:
                    return

            printer = QtGui.QPrinter()
            printer.setOutputFormat(printer.PdfFormat)
            printer.setOrientation(printer.Landscape)
            printer.setOutputFileName(filename)
            printer.setCreator('SPlot')

            filter_ = Qwt.QwtPlotPrintFilter()
            filter_.setOptions(filter_.PrintAll & ~filter_.PrintLegend)
            self._plot.print_(printer, filter_)
        else:
            if not filename:
                filename = QtGui.QFileDialog.getSaveFileName(self, 'Save as', '', 'PNG files (*.png)')
                if not filename:
                    return

            pixmap = QtGui.QPixmap.grabWidget(self._plot_widget)
            pixmap.save(filename, 'png')

    def print_(self, small=False):
        printer = self.printer
        print_dialog = QtGui.QPrintDialog(printer, self)
        if print_dialog.exec_() != QtGui.QDialog.Accepted:
            return

        if small:
            printer.setOrientation(printer.Landscape)
            printer.setPageMargins(0.25, 0.20, 8.0, 4.5, printer.Inch)
        else:
            printer.setOrientation(printer.Portrait)
            printer.setPageMargins(.5, .5, .5, .5, printer.Inch)

        if self._dimension == 1:
            if small:
                for axis in [Qwt.QwtPlot.xBottom, Qwt.QwtPlot.yLeft]:
                    self._plot.setAxisFont(axis, self._plot.small_font)
            filter_ = Qwt.QwtPlotPrintFilter()
            filter_.setOptions(filter_.PrintAll & ~filter_.PrintLegend)
            self._plot.print_(printer, filter_)

            if small:
                for axis in [Qwt.QwtPlot.xBottom, Qwt.QwtPlot.yLeft]:
                    self._plot.setAxisFont(axis, self._plot.label_font)
        else:
            painter = QtGui.QPainter(printer)
            pixmap = QtGui.QPixmap.grabWidget(self.stack)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()

    def load_spec_file(self, fn=''):
        if not fn:
            fn = QtGui.QFileDialog.getOpenFileName(self, 'Open spec file', '', 'Spec files (*)')
            if not fn:
                return

            fn = str(fn)

        self.data.load_spec_file(fn)

        self.scan_widget.reload_data()


def brush_to_color_tuple(brush):
    r, g, b, a = brush.color().getRgbF()
    return (r, g, b)


class MplCanvas(FigureCanvas):
    """
    Canvas which allows us to use matplotlib with pyqt4
    """
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)

        # We want the axes cleared every time plot() is called
        self.axes = fig.add_subplot(1, 1, 1)

        self.axes.hold(False)

        FigureCanvas.__init__(self, fig)

        # self.figure
        self.setParent(parent)

        FigureCanvas.setSizePolicy(self,
                                   QtGui.QSizePolicy.Expanding,
                                   QtGui.QSizePolicy.Expanding)
        FigureCanvas.updateGeometry(self)

        self._title = ''
        self.title_font = {'family': 'serif', 'fontsize': 10}
        self._title_size = 0
        self.figure.subplots_adjust(top=0.95, bottom=0.15)

        window_brush = self.window().palette().window()
        fig.set_facecolor(brush_to_color_tuple(window_brush))
        fig.set_edgecolor(brush_to_color_tuple(window_brush))
        self._active = False

    def _get_title(self):
        return self._title

    def _set_title(self, title):
        self._title = title
        if self.axes:
            self.axes.set_title(title, fontdict=self.title_font)
            #bbox = t.get_window_extent()
            #bbox = bbox.inverse_transformed(self.figure.transFigure)
            #self._title_size = bbox.height
            #self.figure.subplots_adjust(top=1.0 - self._title_size)

    title = property(_get_title, _set_title)


def prune_labels(xlabels, ylabels, xpos, ypos,
                 max_xlabels=LABEL_COUNT, max_ylabels=LABEL_COUNT):
    if max_xlabels <= 0:
        xpos = []
        xlabels = []
    else:
        while len(xpos) > max_xlabels:
            xpos = xpos[::2]
            xlabels = xlabels[::2]

    if max_ylabels <= 0:
        ypos = []
        ylabels = []
    else:
        while len(ypos) > max_ylabels:
            ypos = ypos[::2]
            ylabels = ylabels[::2]

    return xlabels, ylabels, xpos, ypos


class Plot2D(QtGui.QFrame):
    """
    2D plot based on matplotlib
    """
    MODE_HEX = 'hex'
    MODE_PIXEL = 'pixel'
    MODE_CONTOUR = 'contour'
    MODE_SCATTER = 'scatter'
    MODE_3D_SURF = '3d surface'
    MODE_3D_WIRE = '3d wireframe'
    MODE_3D_CONT = '3d contour'
    MODE_3D_CONTF = '3d contour (filled)'
    MODE_DEFAULT = MODE_PIXEL
    CM_DEFAULT = 'jet'

    def __init__(self, parent=None):
        QtGui.QFrame.__init__(self, parent)

        self._layout = QtGui.QGridLayout(self)

        # l b w h
        #axes = self.figure.add_axes([0, 0, 1, 1])
        self.subplots = []
        self._active = False
        self._axis_names = None
        self._image_dims = (-1, -1)
        self._data = None
        self._mode = ''
        self._cur_plots = []
        self._color_map = mpl.cm.get_cmap(Plot2D.CM_DEFAULT)
        self._rows = 0

        self.mode = Plot2D.MODE_DEFAULT

    def create_cmap_previews(self):
        """
        Create the color map previews for the combobox
        """
        cm_names = sorted(cm for cm in mpl.cm.datad.keys()
                          if not cm.endswith('_r'))
        cm_filenames = [os.path.join(CMAP_PREVIEW_PATH, '%s.png' % cm_name)
                        for cm_name in cm_names]

        ret = zip(cm_names, cm_filenames)
        points = np.outer(np.ones(10), np.arange(0, 1, 0.01))
        if not os.path.exists(CMAP_PREVIEW_PATH):
            try:
                os.mkdir(CMAP_PREVIEW_PATH)
            except Exception as ex:
                print('Unable to create preview path: %s' % ex)

            return ret

        for cm_name, fn in zip(cm_names, cm_filenames):
            if not os.path.exists(fn):
                print('Generating colormap preview: %s' % fn)
                canvas = MplCanvas(width=2, height=0.25, dpi=50)
                fig = canvas.figure
                fig.clear()

                ax = fig.add_subplot(1, 1, 1)
                ax.axis("off")
                fig.subplots_adjust(top=1, left=0, right=1, bottom=0)
                cm = mpl.cm.get_cmap(cm_name)
                ax.imshow(points, aspect='auto', cmap=cm, origin='lower')
                try:
                    fig.savefig(fn)
                except Exception as ex:
                    logger.error('Unable to create color map preview "%s"' % fn,
                                 exc_info=True)
                    break

        return ret

    def create_options(self):
        """
        The options frame shown below the axis selector.
        <draw mode> <colormap preview>
        """
        frame = QtGui.QFrame()
        plot_type = QtGui.QComboBox()
        modes = sorted(Plot2D.MODES.keys())
        plot_type.addItems(modes)
        plot_type.setCurrentIndex(modes.index(Plot2D.MODE_DEFAULT))
        self.connect(plot_type, QtCore.SIGNAL('currentIndexChanged(QString)'),
                     lambda mode: self._set_mode(str(mode)))

        color_map = QtGui.QComboBox()
        self.connect(color_map, QtCore.SIGNAL('currentIndexChanged(QString)'),
                     lambda cm: self._set_color_map(str(cm)))

        size = None
        for i, (cm_name, fn) in enumerate(self.create_cmap_previews()):
            if os.path.exists(fn):
                color_map.addItem(QtGui.QIcon(fn), cm_name)
                if size is None:
                    size = QtGui.QPixmap(fn).size()
                    color_map.setIconSize(size)
            else:
                color_map.addItem(cm_name)

            if cm_name == Plot2D.CM_DEFAULT:
                color_map.setCurrentIndex(i)

        #import sys; sys.exit(0)
        layout = QtGui.QGridLayout()
        layout.addWidget(plot_type, 1, 1)
        layout.addWidget(color_map, 1, 2)
        frame.setLayout(layout)

        save_widgets = [
        ]
        return frame, save_widgets

    def _set_color_map(self, cm):
        """
        User changed color map callback.
        """
        print('Color map set to: %s' % cm)
        self._color_map = mpl.cm.get_cmap(cm)
        self.recalculate()

    def _get_axis_names(self):
        return self.axis_names

    def _set_axis_names(self, names):
        if len(names) != 3:
            raise ValueError('Expected sequence of length 3')

        self._axis_names = tuple(names)
        self.recalculate()

    axis_names = property(_get_axis_names, _set_axis_names,
                          doc='A sequence of 3 pvs (x,y,z), one for each axis')

    def set_labels(self, plot, xlabels, ylabels, xpos, ypos):
        """
        Set the labels of the x and y axes.
        """
        axes = plot.axes
        if self._rows <= 2:
            axes.set_xticks(xpos)
            axes.set_xticklabels(xlabels, rotation=90)
            axes.set_yticks(ypos)
            axes.set_yticklabels(ylabels)
        else:
            axes.set_xticks([])
            axes.set_yticks([])

    def set_subplot_count(self, count):
        if len(self.subplots) == count:
            return

        if self.subplots:
            for subplot in self.subplots:
                self._layout.removeWidget(subplot)

                subplot.setParent(None)
                subplot._image_obj = None
                subplot._colorbar = None
                subplot._selector = None
                subplot.axes = None
                subplot.figure.clear()

        if int(sqrt(count)) == sqrt(count):
            rows = sqrt(count)
        else:
            rows = int(sqrt(count)) + 1

        self._rows = rows
        self.subplots = [MplCanvas() for i in range(count)]
        col = 0
        row = 0
        for i, plot in enumerate(self.subplots):
            if i % rows == 0:
                row += 1
                col = 0

            self._layout.addWidget(plot, col, row)
            col += 1

    def _do_pixel(self, canvas, x_data, y_data, z_data, data_set):
        """
        A single pixel plot (see do_pixel)
        """
        if len(z_data) == 0 or len(y_data) == 0 or len(x_data) == 0:
            return False

        if not hasattr(canvas, '_image_obj'):
            canvas._image_obj = None

        w, h = data_set.dimensions[:2]

        image = np.reshape(z_data, (h, w))
        if canvas._image_obj and self._image_dims == (w, h):
            image_obj = canvas._image_obj
            image_obj.set_data(image)
            image_obj.set_clim(min(z_data), max(z_data))
            image_obj.set_cmap(self._color_map)
        else:
            if canvas._image_obj:
                canvas.figure.clear()
                canvas.axes = canvas.figure.add_subplot(1, 1, 1)

            axes = canvas.axes
            canvas._image_obj = axes.imshow(image, interpolation='nearest',
                                            origin='lower', cmap=self._color_map)

            if self._rows <= 2:
                canvas._colorbar = axes.figure.colorbar(canvas._image_obj)

            sel_fcn = lambda ce, re, canvas=canvas: self._region_selected(ce, re, canvas)

            kw = dict(drawtype='box', spancoords='data', minspanx=0, minspany=0)
            canvas._selector = mpl.widgets.RectangleSelector(axes, sel_fcn, **kw)

        return True

    def do_pixel(self, x_data, y_data, z_data, data_set):
        """
        A simple pixel-by pixel plot, where the x and y axes are effectively
        ignored. The dimensions from the scan are necessary, so this cannot
        be used for a 1d scan.

        z_data is a list of the selected Z's
        """
        if data_set is None or data_set.dimension < 2:
            return

        self.set_subplot_count(len(z_data))
        w, h = data_set.dimensions[:2]

        pixels = w * h
        print('pixels=%d w=%d h=%d (len=%d)' % (pixels, w, h, len(z_data[0])))

        def fix_data(data):
            if data is None:
                return []
            elif len(data) < pixels:
                data = list(data) + ([min(data)] * (pixels - len(data)))
                return np.array(data)
            elif len(data) > pixels:
                return np.array(data[:pixels])
            else:
                return data

        z_data = [fix_data(z) for z in z_data]

        xlabels = self._image_x_axis = x_data[:w]
        ylabels = self._image_y_axis = y_data[::w]

        xpos, ypos = range(w), range(h)
        pl = prune_labels(list(xlabels), list(ylabels), xpos, ypos,
                          max_xlabels=self.max_labels, max_ylabels=self.max_labels)
                      #max_xlabels=5, max_ylabels=5)

        xlabels, ylabels, xpos, ypos = pl
        xlabels = ['%.5g' % x for x in xlabels]
        ylabels = ['%.5g' % y for y in ylabels]

        xmin, xmax = min(x_data), max(x_data)
        ymin, ymax = min(y_data), max(y_data)

        for plot, z, title in zip(self.subplots, z_data, self._axis_names[2]):
            if self._do_pixel(plot, x_data, y_data, z, data_set):
                self.set_labels(plot, xlabels, ylabels, xpos, ypos)
            plot.title = title

        self._image_dims = (w, h)
        self.redraw()

    def _do_plot_3d(self, canvas, x_data, y_data, z_data, data_set):
        """
        surface 3d plot
        """
        if len(z_data) == 0 or len(y_data) == 0 or len(x_data) == 0:
            return

        w, h = data_set.dimensions[:2]

        canvas.figure.clear()

        x_data = np.reshape(x_data, (h, w))
        y_data = np.reshape(y_data, (h, w))
        z_data = np.reshape(z_data, (h, w))
        print('3d surface', x_data.shape, y_data.shape, z_data.shape)

        axes = canvas.axes = Axes3D(canvas.figure)

        if self._mode == self.MODE_3D_SURF:
            axes.plot_surface(x_data, y_data, z_data,
                              rstride=1, cstride=1, cmap=self._color_map,
                              linewidth=0, antialiased=False)
                              #, shade=False)
        elif self._mode == self.MODE_3D_WIRE:
            axes.plot_wireframe(x_data, y_data, z_data, rstride=1,
                                cstride=1)
        elif self._mode == self.MODE_3D_CONT:
            axes.contour(x_data, y_data, z_data)
        elif self._mode == self.MODE_3D_CONTF:
            axes.contourf(x_data, y_data, z_data)

    def do_plot_3d(self, x_data, y_data, z_data, data_set):
        """
        Simple 3d surface plot
        """
        if data_set is None or data_set.dimension < 2:
            return

        self.set_subplot_count(len(z_data))
        w, h = data_set.dimensions[:2]

        pixels = w * h
        print('pixels=%d w=%d h=%d (len=%d)' % (pixels, w, h, len(z_data[0])))

        def fix_data(data):
            if len(data) < pixels:
                data = list(data) + ([min(data)] * (pixels - len(data)))
                return np.array(data)
            elif len(data) > pixels:
                return np.array(data[:pixels])
            else:
                return data

        z_data = [fix_data(z) for z in z_data]

        for plot, z, title in zip(self.subplots, z_data, self._axis_names[2]):
            self._do_plot_3d(plot, x_data, y_data, z, data_set)
            plot.title = title

        self._image_dims = (w, h)
        self.redraw()

    def _do_scatter(self, canvas, x_data, y_data, z_data, data_set):
        #w, h = data_set.dimensions[:2]
        try:
            canvas.figure.clear()
            canvas.axes = canvas.figure.add_subplot(111)

            sc = canvas.axes.scatter(x_data, y_data, c=z_data, marker='s', s=200, alpha=0.7)
            canvas.axes.plot(x_data, y_data, marker='', alpha=0.2)
            if self._rows <= 2:
                canvas._colorbar = canvas.axes.figure.colorbar(sc)
            return True
        except Exception as ex:
            print('--> scatter failed: %s' % (ex, ))
            return False

    def do_scatter(self, x_data, y_data, z_data, data_set):
        """
        A scatter plot.
        """
        if data_set is None:  # or data_set.dimension < 2:
            return

        self.set_subplot_count(len(z_data))
        #w, h = data_set.dimensions[:2]

        try:
            xmin, xmax = min(x_data), max(x_data)
            ymin, ymax = min(y_data), max(y_data)
        except:
            print('Unable to get mins/maxes for data')
            return

        #xi = np.linspace(xmin, xmax, w)
        #yi = np.linspace(ymin, ymax, h)

        #xlabels, ylabels, xpos, ypos = prune_labels(list(xi), list(yi), xi, yi,
        #               max_xlabels=self.max_labels, max_ylabels=self.max_labels)

        #xlabels = ['%.5g' % x for x in xlabels]
        #ylabels = ['%.5g' % y for y in ylabels]

        for plot, z, title in zip(self.subplots, z_data, self._axis_names[2]):
            #zi = mpl.mlab.griddata(x_data, y_data, z, xi, yi)
            if self._do_scatter(plot, x_data, y_data, z, data_set):
                plot.axes.set_xlim(xmin, xmax)
                plot.axes.set_ylim(ymin, ymax)
                #self.set_labels(plot, xlabels, ylabels, xpos, ypos)

            plot.title = title

        self.redraw()

    def _do_contour(self, canvas, xi, yi, zi, data_set):
        w, h = data_set.dimensions[:2]
        try:
            canvas.figure.clear()
            canvas.axes = canvas.figure.add_subplot(111)

            canvas.axes.contour(xi, yi, zi, 15, linewidths=0.5, colors='k')
            c2 = canvas.axes.contourf(xi, yi, zi, 15, cmap=self._color_map)

            #canvas.axes.scatter(xi, yi, marker='o', c='b', s=5)
            if self._rows <= 2:
                canvas._colorbar = canvas.axes.figure.colorbar(c2)
            return True
        except Exception as ex:
            print('--> Contour failed: %s (last pixel=%s)' % (ex, data_set.last_grid_point))
            return False

    def do_contour(self, x_data, y_data, z_data, data_set):
        """
        A contour plot.
        """
        if data_set is None or data_set.dimension < 2:
            return

        self.set_subplot_count(len(z_data))
        w, h = data_set.dimensions[:2]

        xmin, xmax = min(x_data), max(x_data)
        ymin, ymax = min(y_data), max(y_data)
        xi = np.linspace(xmin, xmax, w)
        yi = np.linspace(ymin, ymax, h)

        xlabels, ylabels, xpos, ypos = prune_labels(list(xi), list(yi), xi, yi,
                                                    max_xlabels=self.max_labels,
                                                    max_ylabels=self.max_labels)

        xlabels = ['%.5g' % x for x in xlabels]
        ylabels = ['%.5g' % y for y in ylabels]

        for plot, z, title in zip(self.subplots, z_data, self._axis_names[2]):
            zi = mpl.mlab.griddata(x_data, y_data, z, xi, yi)
            if self._do_contour(plot, xi, yi, zi, data_set):
                self.set_labels(plot, xlabels, ylabels, xpos, ypos)
                plot.axes.set_xlim(xmin, xmax)
                plot.axes.set_ylim(ymin, ymax)

            plot.title = title

        self.redraw()

    def _do_hexbin(self, canvas, x_data, y_data, z_data, data_set):
        if data_set is None or data_set.dimension < 2:
            return

        w, h = data_set.dimensions[0], data_set.last_grid_point[0]
        try:
            canvas.figure.clear()
            canvas.axes = canvas.figure.add_subplot(111)
            hexbin = canvas.axes.hexbin(x_data, y_data, z_data,
                                        gridsize=(w, h), cmap=self._color_map)
            canvas._colorbar = canvas.axes.figure.colorbar(hexbin)
        except ValueError as ex:
            # Can't do hexbin on first line, since the x-values
            # are all the same
            pass
        except Exception as ex:
            print('--> Hexbin failed: %s (last pixel=%s)' % (ex, data_set.last_grid_point))
            canvas.axes.clear()
        else:
            canvas.axes.set_xlim(min(x_data), max(x_data))
            canvas.axes.set_ylim(min(y_data), max(y_data))

    def do_hexbin(self, x_data, y_data, z_data, data_set):
        """
        A hex-binning plot.
        """
        if data_set is None or data_set.dimension < 2:
            return

        self.set_subplot_count(len(z_data))
        w, h = data_set.dimensions[:2]

        for plot, z, title in zip(self.subplots, z_data, self._axis_names[2]):
            self._do_hexbin(plot, x_data, y_data, z, data_set)
            #self.set_labels(plot, xlabels, ylabels, xpos, ypos)
            plot.title = title

        self.redraw()

    @property
    def max_labels(self):
        if self._rows > 0:
            return int(LABEL_COUNT / self._rows)
        else:
            return LABEL_COUNT

    def _region_selected(self, click_event, release_event, canvas):
        """A 2d region was selected by the user"""
        def minmax(a, b):
            return min(a, b), max(a, b)

        #x1, x2 = minmax(click_event.xdata, release_event.xdata)
        #y1, y2 = minmax(click_event.ydata, release_event.ydata)
        # ^^
        # Scans should probably be done in the direction/order that the user
        # clicks, so don't assume you should start from the bottom-left:
        x1, x2 = click_event.xdata, release_event.xdata
        y1, y2 = click_event.ydata, release_event.ydata

        if self._mode == Plot2D.MODE_PIXEL:
            w, h = self._image_dims

            ex1, ex2, ey1, ey2 = canvas._image_obj.get_extent()
            x1, x2 = (x1 - ex1), (x2 - ex1)
            y1, y2 = (y1 - ey1), (y2 - ey1)
            #print('adjusted to extents')
            #print('(%f, %f) - (%f, %f)' % (x1, y1, x2, y2))

            x1, x2 = np.interp([x1, x2], range(w), self._image_x_axis)
            y1, y2 = np.interp([y1, y2], range(h), self._image_y_axis)
            #print('interpolated')
            #print('(%f, %f) - (%f, %f)' % (x1, y1, x2, y2))
            self.show_scan_dialog([(x1, x2), (y1, y2)])

    def show_scan_dialog(self, positions):
        dims = self._image_dims
        if dims is None:
            dims = (10, 10)

        # adjust data points, again, for SPEC-command compatibility
        axis_names = [splot_util.strip_readback_suffix(name)
                      for name in self._axis_names[:2]]
        motor_info = [(motor, start, end, points - 1)
                      for motor, (start, end), points
                      in zip(axis_names, positions, dims)
                      ]

        command = splot_util.build_scan_command(motor_info, absolute=True)

        if command.startswith('mesh'):
            command = '%%a%s' % command
        else:
            command = '%' + command

        clipboard = QtGui.QApplication.clipboard()
        clipboard.setText(command)
        print('Command copied to clipboard: %s' % command)
        self._line_edit = QtGui.QLineEdit()
        self._line_edit.setText(command)
        self._line_edit.show()

    def _get_mode(self):
        return self._mode

    def _set_mode(self, mode):
        if mode not in Plot2D.MODES:
            raise ValueError('Unknown 2d plotting mode')
        elif mode == self._mode:
            return

        self._mode = mode
        self._image_dims = (-1, -1)
        for plot in self.subplots:
            plot._image_obj = None
            plot._colorbar = None
            plot._selector = None
            plot.figure.clear()
            plot.axes = plot.figure.add_subplot(1, 1, 1)

        self.recalculate()

    mode = property(_get_mode, _set_mode,
                    doc='The 2d plotting mode (see MODES)')

    MODES = {MODE_HEX: lambda self, *args: self.do_hexbin(*args),
             MODE_PIXEL: lambda self, *args: self.do_pixel(*args),
             MODE_CONTOUR: lambda self, *args: self.do_contour(*args),
             MODE_SCATTER: lambda self, *args: self.do_scatter(*args),
             MODE_3D_SURF: lambda self, *args: self.do_plot_3d(*args),
             MODE_3D_WIRE: lambda self, *args: self.do_plot_3d(*args),
             MODE_3D_CONT: lambda self, *args: self.do_plot_3d(*args),
             MODE_3D_CONTF: lambda self, *args: self.do_plot_3d(*args),
             }

    def redraw(self):
        try:
            for plot in self.subplots:
                plot.axes.relim()
                plot.axes.autoscale_view()
        except:
            pass
        finally:
            for plot in self.subplots:
                plot.draw()

    def _check_axis_name(self, name):
        if isinstance(name, (list, tuple)):
            for n in name:
                if not self._check_axis_name(n):
                    return False
            return True

        if name not in self._data.names:
            for plot in self.subplots:  # TODO
                plot.title = '%s not found' % name
            return False
        return True

    @property
    def axes_valid(self):
        """
        Whether or not the current axis names are available in the data set.
        """
        data_set = self._data
        if not data_set or not self._axis_names:
            return False

        for name in self._axis_names:
            if not self._check_axis_name(name):
                print('name invalid:', name)
                return False

        return True

    def recalculate(self):
        """
        Recalculate and re-plot the data.
        """
        data_set = self._data
        if not self.axes_valid:
            return

        #self.axes.set_title(data_set.command)
        # TODO
        x_data, y_data, z_data = [data_set.data_by_name(name)
                                  for name in self._axis_names]

        mode = self._mode
        plot_fcn = Plot2D.MODES[mode]
        plot_fcn(self, x_data, y_data, z_data, data_set)

    # 2D
    def scan_started(self, new_scan, data_set):
        """
        A notification from PlotData that a scan has started
        """
        self._data = data_set

        #for plot in self.subplots: # TODO
        #    plot.title = command

    def data_updated(self):
        """
        A notification from PlotData that the data points have changed
        """
        pass
        self.recalculate()


def main(spec_file='', xmlrpc_url=''):
    app = QtGui.QApplication(sys.argv)

    style = QtGui.QStyleFactory.create('Cleanlooks')
    app.setStyle(style)

    # ignore ctrl-c, otherwise a cancel in the CLI will kill any plots
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    plot_window = PlotWindow(size=QtCore.QSize(500, 500))
    plot_window.show()

    data = plot_window.data
    data.url = xmlrpc_url

    try:
        if spec_file:
            call_later(0, lambda fn=spec_file:
                       plot_window.load_spec_file(fn))
        app.exec_()
    except:
        logger.error('Plot client main', exc_info=True)


def splot_write(filename):
    try:
        f = open(filename, 'at')
    except Exception as ex:
        print('Unable to open %s (%s)' % (filename, ex))
        f = None

    def write(s, end=''):
        if f:
            print(s, end='', file=f)

    return write


def get_scan_list():
    return ScanWidget.instance.scan_list


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='ECLI Simple Plot')
    parser.add_argument('spec_file', type=str, nargs='?',
                        help='Spec format filename')
    parser.add_argument('--url', type=str, nargs='?',
                        default='http://127.0.0.1:8988/epics_sps',
                        help='ECLI xmlrpc server url')
    parser.add_argument('--output', type=str, nargs='?',
                        default='',
                        help='Redirect output to filename')
    parser.add_argument('--quiet', action='store_true',
                        help='Redirect output to filename')

    args = parser.parse_args()
    if args:
        from ecli_util.misc import OutputStreamHandler
        if args.output:
            print('Splot output redirected to %s' % args.output)
            sys.stdout = OutputStreamHandler(splot_write(args.output))
            sys.stderr = OutputStreamHandler(splot_write(args.output))
        elif args.quiet:
            sys.stdout = OutputStreamHandler()
            sys.stderr = OutputStreamHandler()

        try:
            main(spec_file=args.spec_file, xmlrpc_url=args.url)
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
