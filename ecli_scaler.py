# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_scaler` -- scaler record interface
=============================================

.. module:: ecli_scaler
   :synopsis: Command-line access to scaler records
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import time
import logging

import epics

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import get_plugin
from ecli_util import SimpleTable
from ecli_util.decorators import ShowElapsed
from ecli_util.decorators import ECLIExport
from ecli_util.magic_args import (ecli_magic_args, argument)


logger = logging.getLogger('ECLI.Scaler')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIScaler, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIScaler)


class ECLIScaler(ECLIPlugin):

    """
    ECLI scaler record interface
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    _callbacks = []
    scalers = traitlets.List(traitlets.Unicode,
                             default_value=(),
                             config=True)
    default_count_time = traitlets.Float(1.0, config=True)
    show_timestamp = traitlets.Bool(True, config=True)
    show_elapsed = traitlets.Bool(True, config=True)

    def __init__(self, shell, config):
        self._scaler_devices = {}

        super(ECLIScaler, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIScaler')

    @property
    def logger(self):
        return logger

    def _scalers_changed(self, *args):
        shell = self.shell
        new_scalers = [scaler for scaler in self.scalers
                       if scaler
                       not in shell.user_ns]

        for scaler in new_scalers:
            dev = self._get_device(scaler)
            if dev is not None and util.is_valid_python_identifier(scaler):
                shell.user_ns[scaler] = dev

        # TODO remove old scalers or just leave them in the user namespace?

    def _get_device(self, record):
        record = util.expand_alias(record)
        try:
            return self._scaler_devices[record]
        except KeyError:
            pass

        try:
            dev = epics.devices.Scaler(record)
        except Exception as ex:
            logger.error('Bad scaler "%s" (%s) %s'
                         % (record, ex.__class__.__name__, ex))
        except KeyboardInterrupt:
            logger.warning('Skipping scaler list entry "%s"' % (record, ))
        else:
            self._scaler_devices[record] = dev
            return dev

    @ECLIExport
    def scaler_counts_list(self, scaler, seconds, use_calc=False, partial_ok=True):
        """
        Run the scaler `scaler` for `seconds`, and report
        the results in a list

        :param scaler: Scaler device or record name
        :param seconds: Time in seconds
        :param use_calc: Use calculated values instead of raw values
        :param partial_ok: Return partial counts if interrupted
        """
        cont_mode = scaler.get('CONT')
        scaler.OneShotMode()

        try:
            scaler.Count(ctime=seconds, wait=True)
        except KeyboardInterrupt:
            if not partial_ok:
                return
        finally:
            time.sleep(0.05)  # TODO
            # epics.poll(1e-5)

        try:
            return scaler.Read(use_calc=use_calc)
        finally:
            scaler.put('CONT', cont_mode)

    @ECLIExport
    def scaler_channel_names(self, scaler, default='ch%d'):
        return [name if name else default % i
                for i, name in enumerate(scaler.getNames())]

    @ECLIExport
    def scaler_counts_dict(self, scaler, seconds, **kwargs):
        """
        Run the scaler `scaler` for `seconds`, and report
        the results in a dictionary

        :param scaler: Scaler device or record name
        :param seconds: Time in seconds

        Additional kwarg parameters are passed onto scaler_counts_list.
        """
        names = self.scaler_channel_names(scaler)
        return dict(zip(names, self.scaler_counts_list(scaler, seconds, **kwargs)))

    @ECLIExport
    def scaler_counts_table(self, scaler, seconds, format_='%d', **kwargs):
        """
        Run the scaler `scaler` for `seconds`, and report the results in a
        table

        :param scaler: Scaler device or record name
        :param seconds: Time in seconds

        Additional kwarg parameters are passed onto scaler_counts_list.
        """
        names = self.scaler_channel_names(scaler)
        values = self.scaler_counts_list(scaler, seconds, **kwargs)
        values_str = [format_ % v for v in values]

        header = ['Name', 'Counts']
        table = SimpleTable(header)
        for name, value in zip(names, values_str):
            table.add_row([name, value])

        return table


show_elapsed = ShowElapsed(lambda: get_plugin('ECLIScaler').show_elapsed)


@show_elapsed.wrapper
@ecli_magic_args(ECLIScaler)
@argument('seconds', type=float, nargs='?',
          help='PV')
@argument('-r', '--record', type=AliasedPV,
          help='Record to use')
def ct(margs, self, args):
    """
    $ ct [seconds] [-r/--record record]
    """
    if args.record is not None:
        scalers = [args.record]
    else:
        scalers = self.scalers

    if scalers is None or len(scalers) == 0:
        logging.error('Scaler list undefined (see config ECLIScaler.scalers)')
        return

    if args.seconds is not None:
        seconds = args.seconds
    else:
        seconds = self.default_count_time

    for scaler in scalers:
        if self.show_timestamp:
            print(' %s' % util.timestamp_string())
            print()

        dev = self._get_device(scaler)
        table = self.scaler_counts_table(dev, seconds)
        table.print_()
