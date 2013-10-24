# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_pseudomotor` -- pseudomotor support
==============================================

.. module:: ecli_pseudomotor
   :synopsis: ECLI pseudomotor extension, for creating virtual axes on demand
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

.. warning:: not yet implemented (placeholder)
   (TODO fix up old pseudomotor IOC and make it suitable for this)
"""

from __future__ import print_function
import copy
import logging

# ECLI
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util.decorators import ECLIExport
import ecli_cas.pseudomotor as pseudo

logger = logging.getLogger('ECLI.Pseudomotor')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIPseudomotor,
                                 logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIPseudomotor)


class ECLIPseudomotor(ECLIPlugin):
    """
    ECLI pseudomotor extension, for creating virtual axes on demand
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1), ('ECLIMotor', 1), ('ECLIcas', 1)]
    EXPORTS = {}

    _callbacks = []

    def __init__(self, shell, config):
        super(ECLIPseudomotor, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIPseudomotor')

        self.groups = []

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIPseudomotor')

    @property
    def logger(self):
        return logger


@ECLIExport
def create_motor(pseudo_name, readback_expr, aliases={},
                 rotary=False,
                 **kwargs):
    """
    Create a pseudomotor that mimics an EPICS motor record

    For example,

        >>> create_motor('pseudo', 'm1 * 2.0',
        ...              aliases={'m1': 'IOC:m1'},
        ...              m1='pseudo / 2.0')

    Assuming the CAS prefix is set to ECLI, this will create a pseudomotor
    `ECLI:pseudo`. Its readback value will be updated each time `m1` (which has
    a full record name of `IOC:m1`) is updated, showing twice m1's readback
    value.

        % caget IOC:m1.RBV ECLI:pseudo.RBV
        IOC:m1.RBV        1.0
        ECLI:pseudo.RBV   2.0

        % caput ECLI:pseudo 3.0
        % caget IOC:m1.RBV ECLI:pseudo.RBV
        IOC:m1.RBV        1.5
        ECLI:pseudo.RBV   3.0

    :param pseudo_name: The motor name (appended onto PCASpy prefix)
    :param readback_expr: The expression to be evaluated for the pseudomotor
                          readback value.
    :param aliases: Define aliases for motors
                    e.g., {'m1': 'IOC:m1'}
    :type aliases: dict
    :param rotary: If rotary is set, motor values will be displayed in degrees,
                   but automatically converted to radians when doing calculations.
    :type rotary: bool
    :param kwargs: Each time the pseudomotor is commanded to move, all related
                   motors specified in the kwargs will be commanded to move.

    .. note:: Expressions cannot have colons (:) in them -- that is, motors
              must be valid Python identifiers. Prior to adding the
              pseudomotor, either add aliases via the `aliases` parameter or
              use normal ECLI aliasing.
    """

    plugin = get_plugin('ECLIPseudomotor')
    mplugin = get_plugin('ECLIMotor')
    cas_plugin = get_plugin('ECLIcas')

    core = get_core_plugin()

    all_aliases = copy.deepcopy(core.aliases)
    all_aliases.update(aliases)

    group = pseudo.MotorGroup()

    pseudo_full = all_aliases.get(pseudo_name, pseudo_name)
    logger.info('Pseudomotor: %s (%s) Readback expression: %s' %
                (pseudo_name, pseudo_full, readback_expr))

    # Add the pseudomotor expressions
    group.add_motor(pseudo_name, pseudo_full, readback_expr)

    # And all of the related motor expressions
    for motor, expression in kwargs.items():
        full_pv = all_aliases.get(motor, motor)
        logger.info('Motor: %s (%s) Expression: %s' %
                    (motor, full_pv, expression))

        group.add_motor(motor, full_pv, expression)

    # Check all of the equations first
    group.start()
    logger.debug('Equations checked')

    for motor in kwargs.keys():
        logger.debug('Adding record %s' % motor)
        group.set_record(motor, mplugin.get_motor(motor))

    # Create and add the pseudomotor itself
    pseudomotor = pseudo.PseudoMotor(cas_plugin.manager, group,
                                     pseudo_full, pseudo_name, rotary=rotary)

    pseudomotor.startup()
    group.set_record(pseudo_name, pseudomotor)

    plugin.groups.append(([pseudomotor], group))

    pseudomotor.update_readback()
