# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_opi` -- OPI tools
============================

.. module:: ecli_opi
   :synopsis: OPI (operator interface) tools for ECLI
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
# TODO: how would motor2x, etc fit in?
# TODO: CSS/BOY, MEDM(?)
from __future__ import print_function
import os
import sys
import signal
import logging
import subprocess
import threading

# IPython
import IPython.utils.traitlets as traitlets

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util.decorators import ECLIExport
from ecli_util.magic_args import (ecli_magic_args, argument)

logger = logging.getLogger('ECLI.opi')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIopi, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIopi)


class ECLIopi(ECLIPlugin):
    """
    ECLI OPI launcher
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    _callbacks = []
    #param = traitlets.List(traitlets.Unicode,
    #                       default_value=('m1', 'm2'),
    #                       config=True)
    pv_delimiter = traitlets.Unicode(':', config=True)
    edm_path = traitlets.Unicode('', config=True)

    OPI_EDM = 'edm'
    opis = (OPI_EDM, )

    def __init__(self, shell, config):
        ECLIopi.EXPORTS = {'EDM_DISPLAYS': EDM_DISPLAYS}

        super(ECLIopi, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIopi')
        self.managers = dict((opi, ProcessManager(opi))
                             for opi in self.opis)

    @property
    def logger(self):
        return logger

    #def _param_changed(self, *args):
    #    pass

    def exit(self):
        # Kill all of the subprocesses
        # TODO can this be optional?
        for manager in self.managers.values():
            manager.close()


@ECLIExport
def macros_from_pv(full_pv, allow_partial=True):
    pv, field = util.split_record_field(full_pv)

    plugin = ECLIopi.get_plugin()
    pv_delimiter = plugin.pv_delimiter

    info = {'field': field, 'full_pv': full_pv}

    # TODO this is not actually a standard, and there are cases
    # when it's just not right depending on how the display was written
    if pv_delimiter in pv:
        i = pv.rindex(pv_delimiter)
        info['prefix'], info['record'] = pv[:i + 1], pv[i + 1:]
    elif allow_partial:
        info['prefix'] = ''
        info['record'] = pv
    else:
        # EDM won't allow for unspecified macros, so arbitrarily
        # break up the pv (?)
        info['prefix'] = pv[:5]
        info['record'] = pv[5:]

    return info


EDM_DEFAULT_DISPLAYS = {
    'motor': 'motorx_all',
    'scaler': 'scaler_full',
}


__motor_display = {'prefix': 'P',
                   'record': 'M',
                   'args': [],
                   }
EDM_DISPLAYS = {
    'motorx': __motor_display,
    'motorx_all': __motor_display,
    'motorx_more': __motor_display,
    'motorxmsta_detail': __motor_display,
    'motorx_setup': __motor_display,
    'motorx_tiny': __motor_display,
    'scaler_full': {'prefix': 'P',
                    'record': 'S',
                    'args': [],
                    },
}


def edm_display_macros(display, macro_dict):
    disp_info = EDM_DISPLAYS[display]

    m = {disp_info['prefix']: macro_dict['prefix'],
         disp_info['record']: macro_dict['record'],
         }
    for arg in disp_info['args']:
        m[arg] = macro_dict[arg]

    m_pairs = zip(m.keys(), m.values())
    return ','.join('%s=%s' % (pair) for pair in m_pairs)


def ignore_sigint():
    # Ignore the SIGINT signal by setting the handler to the standard
    # signal handler SIG_IGN. (see http://stackoverflow.com/questions/5045771 )
    #
    # Without this, background subprocesses intercept ctrl-c and quit
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class ProcessManager(object):
    def __init__(self, group='', kill_on_close=False, daemon=True):
        self.threads = []
        self.processes = []
        self.group = group
        self.daemon = daemon
        self.kill_on_close = kill_on_close

    def _run_thread(self, sh):
        logger.debug('Running %s in subprocess' % sh)

        proc = None
        try:
            proc = subprocess.Popen(sh, shell=True, preexec_fn=ignore_sigint)
            self.processes.append(proc)
            ret = proc.wait()
        except Exception as ex:
            logger.error('Execution of "%s" failed: %s' % (sh, ex))
        else:
            logger.info('Process "%s" finished (%d)' % (sh, ret))

        if proc in self.processes:
            self.processes.remove(proc)

    def check_threads(self):
        for th in list(self.threads):
            if not th.is_alive():
                self.threads.remove(th)

    def run(self, sh):
        if len(self.threads) > 3:
            self.check_threads()

        thread = threading.Thread(target=self._run_thread, args=(sh, ))
        thread.setDaemon(self.daemon)
        self.threads.append(thread)
        thread.start()

    def close(self):
        self.check_threads()

        if self.kill_on_close:
            for process in self.processes:
                logger.info('Terminating subprocess %s' % (process, ))
                process.kill()

            for th in self.threads:
                th.join()


@ecli_magic_args(ECLIopi)
@argument('pv', type=AliasedPV,
          help='PV')
@argument('display', type=str, nargs='?',
          help='Display name')
@argument('-e', '--edit', action='store_const', const=True,
          help='Edit instead of execute the display')
@argument('-b', '--background', action='store_const', const=True,
          help='Run in the background')
def edm(margs, self, args):
    """
    $ edm pv [display] [-e] [-b]
    """
    macros = macros_from_pv(args.pv, allow_partial=False)

    if args.display is not None:
        display = args.display
    else:
        rtype = util.get_record_type(args.pv)
        display = EDM_DEFAULT_DISPLAYS[rtype]

    plugin = ECLIopi.get_plugin()

    exe = os.path.join(plugin.edm_path, 'edm')

    m_str = edm_display_macros(display, macros)
    logger.debug("Display: %s Macros: %s Macro string: %s" %
                 (display, macros, m_str))
    if sys.platform.startswith('win'):
        to_run = ['"%s"' % exe]
    else:
        to_run = [exe]

    if args.edit:
        pass
    else:
        to_run.append('-x')

    to_run.append('-m "%s"' % m_str)
    to_run.append(display)
    to_run = ' '.join(to_run)
    print('Running: %s' % to_run)

    if args.background:
        plugin.managers[plugin.OPI_EDM].run(to_run)
    else:
        shell = get_core_plugin().shell
        shell.system(to_run)
