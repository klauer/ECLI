# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_cas.cas` -- ECLI Channel Access Server
=================================================

.. module:: ecli_cas.cas
   :synopsis: ECLI channel access server extension
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
# TODO callback option on add_pv (specify cb name, then core.add_callback?)
# TODO create simple Python calc-style record
# TODO add pseudomotor functionality through this
from __future__ import print_function
import logging

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (
    argument, magic_arguments, parse_argstring)

# ECLI
from ecli_plugin import ECLIPlugin
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util.decorators import ECLIExport

# pcaspy
import pcaspy

from . import (PCAS_TYPES, PCAS_SEVERITY)
from . import (PVManager, )

logger = logging.getLogger('ECLIcas')


# Loading of this extension
def load_ipython_extension(ipython):
    core = get_core_plugin()
    if core is None:
        logger.error('ECLI core not loaded')
        return

    try:
        core.unregister_extension('ECLIcas')
    except:
        pass

    instance = core.register_extension(ECLIcas, globals_=globals())
    if instance is not None:
        instance._register_callbacks()


def unload_ipython_extension(ipython):
    core = get_core_plugin()
    core.unregister_extension('ECLIcas')

    pcaspy.asCaStop()
# -


class ECLIcas(ECLIPlugin):
    """
    ECLI channel access server
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}

    _callbacks = []
    prefix = traitlets.Unicode('ECLI:', config=True)

    def __init__(self, shell, config):
        # Export the severities to the user namespace (NO_ALARM, etc.)
        severities = [(key, getattr(pcaspy.alarm.Severity, key))
                      for key in dir(pcaspy.alarm.Severity)
                      if key.endswith('_ALARM')]
        ECLIcas.EXPORTS = dict(severities)

        super(ECLIcas, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIcas')

        # Force using the prefix assigned at the start
        self._prefix = self.prefix
        self.manager = PVManager(self._prefix)
        self.manager.run()

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIcas')

    @staticmethod
    def get_pv_manager():
        return get_plugin('ECLIcas').manager

    @staticmethod
    def get_driver():
        try:
            return ECLIcas.get_pv_manager().driver
        except:
            return None

    @property
    def logger(self):
        return logger

    def _prefix_changed(self, name, old, new):
        if old is not None:
            logger.warning('Prefix will not be changed until next restart')


@ECLIExport
def create_pv(pvname, write_callback=None, **kwargs):
    '''
    Create a PV using PCASpy

    :param pvname: the name of the PV to create (not including the ECLIcas prefix)
    :param write_callback: a function (callable) to call when the PV is written to via caput
            Callbacks are called with cb(pv=CAPV instance, pvname=name, value=value, ...)

    :param kwargs: See below for possible kwargs (pcaspy documentation for more)

    ======   =================================   ==========  ===================================================
    Field    Option                              Default     Description
    ======   =================================   ==========  ===================================================
    type     enum, string, char, float or int    float       PV data type
    count    positive integer number             1           Number of elements
    enums    string list                         []          String representations when type is enum
    states   list of severity state.             []          Severity states when type is enum [NO_ALARM, MINOR_ALARM, MAJOR_ALARM, INVALID_ALARM]
    prec     positive integer number             0           Precision when type is 'float'
    unit     string                                          Physical meaning of data
    lolim    float number                        0.0         Data low limit for graphics display
    hilim    float number                        0.0         Data high limit for graphics display
    low      float number                        0.0         Data low limit for alarm
    high     float number                        0.0         Dat high limit for alarm
    lolo     float number                        0.0         Data low low limit for alarm
    hihi     float number                        0.0         Data high high limit for alarm
    scan     float number                        0.0         Data scan period. 0.0 means passive
    asyn     boolean                             False       PV data process finishes asynchronously or not
    asg      string                                          Access security group name
    value    python builtin data type            0           Initial value
    ======   =================================   ==========  ===================================================
    '''

    pvmanager = ECLIcas.get_pv_manager()
    return pvmanager.add_pv(pvname, **kwargs)


@magic_arguments()
@argument('name', type=str,
          help='PV name (added onto prefix)')
@argument('type', choices=PCAS_TYPES, default='float', nargs='?',
          help='PV data type')
@argument('-c', '--count', type=int,
          help='Number of elements')
@argument('-e', '--enums', type=str, nargs='*',
          help='String representations when type is enum')
@argument('-s', '--states', choices=PCAS_SEVERITY, nargs='*',
          help='Severity states when type is enum')
@argument('-p', '--prec', type=int,
          help='Precision when type is float')
@argument('-u', '--unit', type=str,
          help='Physical meaning of data')
@argument('-l', '--lolim', type=float,
          help='Data low limit for graphics display')
@argument('-h', '--hilim', type=float,
          help='Data high limit for graphics display')
@argument('-al', '--low', type=float,
          help='Data low limit for alarm')
@argument('-ah', '--high', type=float,
          help='Data high limit for alarm')
@argument('-aL', '--lolo', type=float,
          help='Data low low limit for alarm')
@argument('-aH', '--hihi', type=float,
          help='Data high high limit for alarm')
@argument('-S', '--scan', type=float,
          help='Data scan period. 0.0 means passive')
@argument('-a', '--asyn', const=True, action='store_const',
          help='PV data process finishes asynchronously or not')
@argument('-g', '--asg', type=str,
          help='Access security group name')
@argument('-v', '--value', type=str,  # pcaspy takes care of type conversion
          help='Initial value')
def _create_pv(self, arg):
    """
    Create a PV through pcaspy
    """
    args = parse_argstring(_create_pv, arg)
    if args is None:
        return

    pvmanager = ECLIcas.get_pv_manager()
    kwargs = dict([(k, v) for k, v in args._get_kwargs()
                   if v is not None])

    if 'states' in kwargs:
        kwargs['states'] = [getattr(pcaspy.alarm.Severity, state)
                            for state in kwargs['states']]

    pvmanager.add_pv(args.name, **kwargs)