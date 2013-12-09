# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_pseudomotor` -- pseudomotor support
==============================================

.. module:: ecli_pseudomotor
   :synopsis: ECLI pseudomotor extension, for creating virtual axes on demand
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""

from __future__ import print_function
import copy
import logging

import epics

# ECLI
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import get_plugin
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
        self.pseudo_to_group = {}

    @property
    def logger(self):
        return logger

    @ECLIExport
    def create_motors(self, create=[], aliases={},
                      desc='', rotary=[],
                      **kwargs):
        """
        Create pseudomotors that mimic an EPICS motor records

        For example,

            >>> create_motors(create=['pseudo1', 'pseudo2'],
            ...               m1='pseudo1 / 2.0',
            ...               pseudo1='m1 * 2',
            ...               pseudo2='(m1 * 2) + 0.1',
            ...               aliases={'m1': 'IOC:m1'},
            ...               )

        Assuming the CAS prefix is set to ECLI:, this will create two pseudomotors
        `ECLI:pseudo1` and `ECLI:pseudo2`. Their readback values will be updated
        each time `m1` (which has a full record name of `IOC:m1`) is updated,
        showing twice m1's readback value (and with a slight offset).

            % caget IOC:m1.RBV ECLI:pseudo1.RBV ECLI:pseudo2.RBV
            IOC:m1.RBV        1.0
            ECLI:pseudo1.RBV   2.0
            ECLI:pseudo2.RBV   2.1

            % caput ECLI:pseudo 3.0
            % caget IOC:m1.RBV ECLI:pseudo1.RBV ECLI:pseudo2.RBV
            IOC:m1.RBV        1.5
            ECLI:pseudo1.RBV   3.0
            ECLI:pseudo2.RBV   3.1

        :param create: The pseudo motor names (appended onto PCASpy prefix)
                       The expression to be evaluated for the pseudomotor readback value
                       should be set as a keyword argument.
        :param aliases: Define aliases for motors
                        e.g., {'m1': 'IOC:m1'}
        :type aliases: dict
        :param rotary: If a motor is the rotary list, motor values will be displayed in degrees,
                       but automatically converted to radians when doing calculations.
        :type rotary: list
        :param kwargs: Each time the pseudomotor is commanded to move, all related
                       motors specified in the kwargs will be commanded to move.

        :returns: tuple containing (Pseudomotor instance list, MotorGroup instance)
        .. note:: Expressions cannot have colons (:) in them -- that is, motors
                  must be valid Python identifiers. Prior to adding the
                  pseudomotor, either add aliases via the `aliases` parameter or
                  use normal ECLI aliasing.
        """

        if not create:
            raise ValueError('No motors to create')

        mplugin = get_plugin('ECLIMotor')
        cas_plugin = get_plugin('ECLIcas')

        core = self.core

        all_aliases = copy.deepcopy(core.aliases)
        all_aliases.update(aliases)

        group = pseudo.MotorGroup(aliases=all_aliases)

        pseudo_names = list(create)

        for pseudo_name in pseudo_names:
            if pseudo_name in self.pseudo_to_group:
                logger.info('Removing previously created pseudomotor of the same name (%s)' % pseudo_name)
                self.delete_pseudomotor(pseudo_name)

        pseudos_full = [all_aliases.get(pseudo_name, pseudo_name)
                        for pseudo_name in pseudo_names]

        for pseudo_name, pseudo_full in zip(pseudo_names, pseudos_full):

            readback_expr = kwargs[pseudo_name]
            logger.info('Pseudomotor: %s (%s) Readback expression: %s' %
                        (pseudo_name, pseudo_full, readback_expr))

            # Add the pseudomotor expressions
            group.add_motor(pseudo_name, pseudo_full, readback_expr)

        # And all of the related motor expressions
        for motor, expression in kwargs.items():
            if motor in pseudo_names:
                continue

            full_pv = all_aliases.get(motor, motor)
            logger.info('Motor: %s (%s) Expression: %s' %
                        (motor, full_pv, expression))

            group.add_motor(motor, full_pv, expression)

        # Check all of the equations first
        group.start()
        logger.debug('Equations checked')

        for param in kwargs.keys():
            if param in pseudo_names:
                continue

            logger.debug('Adding record %s' % param)

            full_param = all_aliases.get(param, param)
            rtype = util.get_record_type(full_param)
            if rtype == 'motor':
                record = mplugin.get_motor(param)
                group.set_record(param, record)

        pseudos = []
        # Create the pseudomotor instance itself
        for pseudo_name, pseudo_full in zip(pseudo_names, pseudos_full):
            p = pseudo.PseudoMotor(cas_plugin.manager, group,
                                   pseudo_full, pseudo_name,
                                   rotary=pseudo_name in rotary)
            pseudos.append(p)
            group.set_record(pseudo_name, p)

        # And start them up
        for pseudomotor in pseudos:
            pseudomotor.startup()

        for pseudo_name, pseudomotor in zip(pseudo_names, pseudos):
            pseudomotor.update_readback()

            self.pseudo_to_group[pseudo_name] = group

        self.groups.append(group)
        return pseudos, group

    @ECLIExport
    def create_motor(self, pseudo_name, readback_expr, aliases={},
                     desc='', rotary=False, **kwargs):
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
        :param desc: Motor description (defaults to the motor alias)
        :param kwargs: Each time the pseudomotor is commanded to move, all related
                       motors specified in the kwargs will be commanded to move.

        :returns: tuple containing (Pseudomotor instance, MotorGroup instance)

        .. note:: Expressions cannot have colons (:) in them -- that is, motors
                  must be valid Python identifiers. Prior to adding the
                  pseudomotor, either add aliases via the `aliases` parameter or
                  use normal ECLI aliasing.
        """
        if rotary:
            rotary_list = [pseudo_name]
        else:
            rotary_list = []

        all_motors = copy.deepcopy(kwargs)
        all_motors[pseudo_name] = readback_expr
        pseudos, group = self.create_motors(create=[pseudo_name],
                                            aliases=aliases,
                                            rotary=rotary_list,
                                            **all_motors)
        pseudo = pseudos[0]
        pseudo.put('DESC', desc)
        return pseudo, group

    @ECLIExport
    def delete_pseudomotor(self, pseudo_name):
        """
        Delete a pseudomotor by name (deletes the whole group currently)
        """
        group = self.pseudo_to_group[pseudo_name]
        for name, record in group.records:
            if isinstance(record, pseudo.PseudoMotor):
                record.shutdown()
            if name in self.pseudo_to_group:
                del self.pseudo_to_group[name]

        self.groups.remove(group)
