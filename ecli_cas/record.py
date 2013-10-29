# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_cas.cas.record` -- CAS Record
============================================

.. module:: ecli_cas.cas.record
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function
import functools

# ECLI
from . import record_info


def fix_type(type_):
    if type_ in ('ulong', 'long'):
        return 'int'
    elif type_ in ('uchar', 'char'):
        return 'int'
    return type_


def create_field_info(type_, defaults):
    info = {'type': fix_type(type_)}
    if type_ == 'enum':
        default, menu_items = defaults
        info['enums'] = menu_items
    else:
        default, lolim, hilim = defaults
        info['lolim'] = lolim
        info['hilim'] = hilim
        info['prec'] = 6

    info['value'] = default
    return info


class NoCallbacks(object):
    """
    Context manager that disables PV updated callbacks for a block
    """
    def __init__(self, record):
        self.record = record

    def __enter__(self):
        self.record._callbacks = False

    def __exit__(self, type_, value, traceback):
        self.record._callbacks = True


class CASRecord(object):
    def __init__(self, manager, name, rtype='ai', dtype='Soft Channel',
                 **fields):
        self.name = name
        self.manager = manager

        # Mimic epics.Device:
        self._prefix = '%s%s.' % (manager.prefix, name)

        self.aliases = {}
        self.fields = {}
        self._callbacks = True
        for field, (alias, type_, defaults) in record_info.RECORD_FIELDS.items():
            info = create_field_info(type_, defaults)
            self.add_field(field, info, alias=alias)

        for field, info_dict in fields.iteritems():
            self.add_field(field, info_dict)

        self.put('data_type', dtype)
        self.put('record_type', rtype)

    def _no_callbacks(self):
        return NoCallbacks(self)

    def get_field_name(self, field):
        if field:
            return '%s.%s' % (self.name, field)
        else:
            return self.name

    def _wrap_cb(self, cb):
        @functools.wraps(cb)
        def wrapped(*args, **kwargs):
            if self._callbacks:
                return cb(*args, **kwargs)
            else:
                return True
        return wrapped

    def add_field(self, field, info_dict, alias=None):
        if field == 'VAL':
            # The record itself should point to .VAL
            self.add_field('', info_dict, alias=alias)

        full_field = self.get_field_name(field)
        self.fields[field] = pvi = self.manager.add_pv(full_field, **info_dict)
        if alias is not None:
            self.aliases[alias] = field

        for name in (field, alias):
            if name is None:
                continue

            try:
                field_cb = getattr(self, '%s_updated' % name.lower())
                pvi.add_write_callback(self._wrap_cb(field_cb))
                #print('adding callback', name)
            except AttributeError:
                pass

        return pvi

    def remove_field(self, field):
        try:
            field = self.aliases[field]
        except KeyError:
            pass

        full_field = self.get_field_name(field)
        self.manager.remove_pv(full_field)

        del self.fields[field]

    def remove_all(self):
        for field in list(self.fields.keys()):
            self.remove_field(field)

    def __getitem__(self, key):
        if key in self.aliases:
            key = self.aliases[key]

        return self.fields[key]

    def set_field(self, field, value):
        pvi = self[field]
        pvi.set_value(value)

    put = set_field

    def process_updated(self, value=None, **kwargs):
        if value is not None and value:
            print('Record processed', value, kwargs)
        pass


def _test():
    from . import PVManager
    import epics

    manager = PVManager('ECLI:')
    manager.run()

    record = CASRecord(manager, 'test', VAL=dict(type='str', value='test'))
    print(epics.caget('ECLI:test.VAL'))
    print(epics.caput('ECLI:test.PROC', 1))

    import time
    time.sleep(10)
    record.remove_all()
