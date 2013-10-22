# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_cas.pseudomotor` -- pseudomotor support
==================================================

.. module:: ecli_pseudomotor
   :synopsis: ECLI pseudomotor support
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""

from __future__ import print_function
import logging
import math
import sys

import epics
import ast

from . import SoftMotor
from . import motor_info as mi


logger = logging.getLogger('ECLI.pseudomotor')


class EquationSet(object):
    """
    Holds a set of inter-related equations and their
    corresponding motor/pseudomotor records
    """
    # TODO: this should really just be a PseudomotorGroup like before --
    #       it makes much more sense to monitor all the motors in a group only
    #       once
    def __init__(self, globals=None):
        self.variables = {}
        self._globals = globals
        self._validated = False

        if globals is None:
            self._globals = self._build_globals()
            for fcn in ('sin', 'asin', 'cos', 'acos', 'tan', 'atan', 'atan2', 'pi', 'pow'):
                self._globals[fcn] = getattr(math, fcn)

    def start(self):
        for name, record in self.records:
            if isinstance(record, PseudoMotor):
                record.startup()

    @property
    def validated(self):
        return self._validated

    def _build_globals(self, allowed_modules=['numpy', 'math', '__builtins__']):
        return dict((module, globals()[module]) for module in allowed_modules
                    if module in globals())

    def add_motor(self, variable, record, equation):
        if variable in self.variables:
            raise KeyError('Variable already exists: %s' % variable)

        self.variables[variable] = {'full_pv': record,
                                    'equation': equation,
                                    'record': None,
                                    'related': set(),
                                    'last_value': 0.0,
                                    }

        self._validated = False

    def _validate_equation(self, variable, eq):
        root = ast.parse(eq)
        identifiers = set([node.id for node in ast.walk(root)
                          if isinstance(node, ast.Name)])

        for ident in identifiers:
            if ident in self.variables:
                self.variables[variable]['related'].add(ident)
                self.variables[ident]['related'].add(variable)
            elif ident in self._globals:
                pass
            else:
                raise ValueError('Unknown identifier %s' % ident)

        return eq

    def get_equation(self, variable):
        return self.variables[variable]['equation']

    def check_equations(self):
        if self._validated:
            return True

        for variable in self.variables.keys():
            eq = self.get_equation(variable)
            self._validate_equation(variable, eq)

        self._validated = True
        return self._validated

    def get_record(self, variable):
        return self.variables[variable]['record']

    def set_record(self, variable, record):
        self.variables[variable]['record'] = record

    def get_related_records(self, variable):
        return [(var, self.variables[var]['record'])
                for var in self.variables[variable]['related']]

    @property
    def records(self):
        for variable, info in self.variables.items():
            yield variable, info['record']

    def variable_dict(self):
        ret = {}
        for variable, record in self.records:
            if isinstance(record, PseudoMotor):
                if record._rotary:
                    ret[variable] = record.request_position * math.pi / 180.0
                else:
                    ret[variable] = record.request_position
            elif isinstance(record, epics.Motor):
                ret[variable] = record.get_position(readback=True)
            else:
                ret[variable] = record.get()

        return ret

    def evaluate(self, variable, locals_=None):
        if locals_ is None:
            locals_ = self.variable_dict()

        entry = self.variables[variable]
        eq = self.get_equation(variable)

        try:
            ret = eval(eq, self._globals, locals_)
        except Exception as ex:
            logger.debug('Unable to calculate new position', exc_info=True)
            logger.debug('* Expression: %s' % eq)
        else:
            record = entry['record']
            if isinstance(record, PseudoMotor) and record._rotary:
                entry['last_value'] = ret * 180.0 / math.pi
            else:
                entry['last_value'] = ret

        return entry['last_value']

    def evaluate_related(self, variable):
        info = self.variables[variable]

        ret = {}
        for related in info['related']:
            ret[related] = self.evaluate(related)
        return ret


class PseudoMotor(SoftMotor):
    _globals = None
    def __init__(self, manager, equations, alias, record_name,
                 readback_calc=None, rotary=False):
        """
        :param manager: the CAS PV manager
        :param alias: alias
        :param record_name: pseudomotor record name
        :param readback_calc: equation used to update readback value
                              e.g., (m1 + m2) would sum readbacks from m1 and m2,
                              making the readback for this pseudomotor. If unset,
                              uses the all_motor database
        """
        logger.debug('Pseudo motor: %s = %s' % (record_name, readback_calc))

        self.equations = equations
        if not self.equations.validated:
            self.equations.check_equations()

        self.equations.set_record(alias, self)

        SoftMotor.__init__(self, manager, record_name)

        self._related_motors = None
        self._readback_calc = self.equations.get_equation(alias)
        self._waiting = set()
        self._rotary = rotary
        self._alias = alias
        self._records = {}

    def startup(self):
        for name, info in self.related_motors.items():
            rec = info['record']
            rec.set_callback(mi.MOTOR_USER_READBACK,
                             lambda **kwargs: self.update_readback())
            rec.set_callback(mi.MOTOR_DONE_MOVE,
                             lambda motor=name, **kwargs: self.related_finished(motor, **kwargs))

        self.calculate_range()

    def calculate_range(self):
        """
        Assuming that limits of all real motors may give minimal/maximal positions
        for the pseudomotor, iterate through the combinations and set rough
        pseudomotor limits.
        """
        mins = {}
        maxes = {}

        for name, info in self.related_motors.items():
            rec = info['record']
            low_limit = getattr(rec, mi.MOTOR_USER_LOW_LIMIT)
            high_limit = getattr(rec, mi.MOTOR_USER_HIGH_LIMIT)
            mins[name] = low_limit
            maxes[name] = high_limit

            logger.debug('Motor %s low: %s high: %s' %
                         (name, low_limit, high_limit))

        real_positions = {}
        iterations = 2 ** len(self.related_motors)

        alias = self._alias
        i = 0
        while i < iterations:
            j = 1
            for name, info in self.related_motors.items():
                if (i & j) == 0:
                    real_positions[name] = mins[name]
                else:
                    real_positions[name] = maxes[name]

                j *= 2

            readback = self.equations.evaluate(self._alias, locals_=real_positions)
            if alias not in mins or mins[alias] > readback:
                mins[alias] = readback

            if alias not in maxes or maxes[alias] < readback:
                maxes[alias] = readback

            i += 1

        if alias in mins:
            self.user_low_limit_updated(mins[alias])
            logger.debug('Set pseudomotor low limit %s: %s' %
                         (alias, mins[alias]))

        if alias in maxes:
            self.user_high_limit_updated(maxes[name])
            logger.debug('Set pseudomotor high limit %s: %s' %
                         (alias, maxes[alias]))

    @property
    def related_motors(self):
        def make_entry(name, record):
            return {'record': record,
                    'finished': record.get(mi.MOTOR_DONE_MOVE),
                    }

        if self._related_motors is None:
            records = self.equations.get_related_records(self._alias)
            motors = dict([(name, make_entry(name, record)) for name, record in records
                           if isinstance(record, epics.Motor)])

            self._related_motors = motors
        return self._related_motors

    def go_updated(self, value=None, **kwargs):
        # If stop/pause/go is pressed, notify all related motors
        SoftMotor.go_updated(self, value)

        for name, info in self.related_motors.items():
            record = info['record']
            record.put(mi.MOTOR_GO, value)

    def move(self, amount, relative=False):
        if self._go != mi.MOTOR_GO_GO:
            return

        if relative:
            pos = self._readback + amount
        else:
            pos = amount

        logger.debug('-> Pseudo move %s to %s' % (self, pos))

        SoftMotor.move(self, pos, relative=False)

        def put_complete(motor):
            if motor in self._waiting:
                logger.debug('Put complete: %s' % motor)
                self._waiting.remove(motor)
            else:
                logger.debug('Put complete: %s (not in list?)' % motor)

            if not self._waiting:
                self.done_moving = True

        self.done_moving = False

        new_positions = self.equations.evaluate_related(self._alias)
        for motor, new_pos in new_positions.items():
            record = self.equations.get_record(motor)

            logger.debug('Setting %s.VAL %g' % (record, new_pos))
            user_pv = '%sVAL' % (record._prefix, )

            pvi = epics.PV(user_pv)
            self._waiting.add(pvi)

            pvi.put(new_pos, timeout=None,
                    callback=lambda motor=motor, pvi=pvi, **kwargs: put_complete(pvi))

        if not self._waiting:
            self.done_moving = True

    def update_readback(self):
        readback = self.equations.evaluate(self._alias)
        self._set_readback(readback)

    def related_finished(self, motor_name, value=None, **kwargs):
        entry = self._related_motors[motor_name]
        entry['finished'] = (value != 0)

        done = all(entry['finished'] for name, entry in self.related_motors.items())
        self.done_moving = done


def _test():
    eq_set = EquationSet()
    eq_set.add_motor('m1', 'IOC:m1', '0.5 * pseudo1')
    eq_set.add_motor('m2', 'IOC:m2', '0.6 * pseudo1')
    eq_set.add_motor('pseudo1', 'ECLI:test', '2.0 * m1')
    #eq_set.check_equations()

    from . import PVManager
    import epics

    manager = PVManager('ECLI:')
    manager.run()

    eq_set.set_record('m1', epics.Motor('IOC:m1'))
    eq_set.set_record('m2', epics.Motor('IOC:m2'))
    pseudo = PseudoMotor(manager, eq_set, 'pseudo1', 'test')

    eq_set.start()

    pseudo.update_readback()
    print('calculated rbv is', epics.caget('ECLI:test.RBV'))

    print(epics.caget('ECLI:test.VAL'), pseudo)
    import time
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        pass

    print('Move done')

    print('pseudo rbv', epics.caget('ECLI:test.RBV'))
    print('m1 rbv', epics.caget('IOC:m1.RBV'))
    print('m2 rbv', epics.caget('IOC:m2.RBV'))
