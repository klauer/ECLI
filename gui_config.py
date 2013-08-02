# -*- coding: utf-8 -*-
"""
:mod:`gui_config` -- ECLI GUI configuration
===========================================

.. module:: gui_config
    :synopsis: ECLI GUI configuration, by way of guidata (http://code.google.com/p/guidata)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""
from __future__ import print_function

import logging
try:
    import guidata
    import guidata.dataset.datatypes as dt
    import guidata.dataset.dataitems as di
    from guidata.dataset.datatypes import DataSetGroup
except Exception as ex:
    logging.warning('guidata not installed/functioning; GUI configuration dialogs disabled.')
    ex_str = 'guidata import failure (%s) %s' % (ex.__class__.__name__, ex)
    logging.debug(ex_str)
    raise ImportError(ex_str)

import IPython.utils.traitlets as traitlets

from ecli_util import (get_plugin, get_core_plugin)

trait_map = {traitlets.Int: di.IntItem,
             #traitlets.Unicode: di.StringItem,
             #traitlets.Unicode: di.TextItem,
             traitlets.Bool: di.BoolItem,
             traitlets.Float: di.FloatItem,
             traitlets.Dict: di.DictItem,
             }

import numpy as np

# most likely a numpy array is of floats, but not necessarily
# -- override it with gui_class if necessary
trait_instance_map = {np.ndarray: di.FloatArrayItem,
                      'numpy.ndarray': di.FloatArrayItem,
                      file: di.FileOpenItem,
                      'file': di.FileOpenItem,
                      }


def map_trait(instance, name, trait):
    trait_class = trait.__class__
    value = getattr(instance, name)

    metadata = trait.get_metadata('gui')
    if not isinstance(metadata, dict):
        metadata = {}

    gui_args = metadata.get('args', [])
    gui_kwargs = metadata.get('kwargs', {})
    gui_class = metadata.get('class', None)
    if gui_class is not None:
        gui_class = getattr(di, gui_class)
        return gui_class(name, *gui_args, **gui_kwargs)

    if trait_class in trait_map:
        ditem = trait_map[trait_class]
    elif trait_class is traitlets.Unicode:
        if '\n' in value or '\r' in value or len(value) > 100:
            ditem = di.TextItem
        else:
            ditem = di.StringItem
    elif trait_class is traitlets.Instance:
        if trait.klass is np.ndarray or trait.klass == 'numpy.ndarray':
            value = value.tolist()
        try:
            ditem = trait_instance_map[trait.klass]
        except KeyError:
            logging.debug('Unhandled traitlet Instance %s' % trait.klass)
            return None

    elif trait_class is traitlets.List:
        # TODO this needs to be handled specially
        # apparently with a custom dialog, also
        return None
    else:
        return None

    if 'default' in gui_kwargs:
        return ditem(name, *gui_args, **gui_kwargs)
    else:
        return ditem(name, default=value, *gui_args, **gui_kwargs)


def gui_config(remove_prefixes=['_']):
    shell = get_core_plugin().shell
    datasets = []
    all_items = {}
    for configurable in sorted(shell.configurables,
                               key=lambda c: c.__class__.__name__):
        items = {}

        conf_name = configurable.__class__.__name__
        for name, trait in configurable.traits().items():
            skip = False
            for prefix in remove_prefixes:
                if name.startswith(prefix):
                    skip = True
                    break

            if not skip:
                mapped = map_trait(configurable, name, trait)
                if mapped is not None:
                    item_key = '%s.%s' % (conf_name, name)
                    items[item_key] = mapped
                    all_items[item_key] = mapped

        if items:
            ds_class = type(conf_name, (dt.DataSet,), items)
            datasets.append(ds_class())

    app = guidata.qapplication()  # <-- this already checks if one exists
    group = DataSetGroup(datasets, title='ECLI Configuration')
    group.edit()

    #for ds in datasets:
    #    print('------------- %s ---------------' % (ds.__class__.__name__, ))
    #    print(ds)
    #    print()
    #    print()
    for key, item in all_items.items():
        print(key, item)

    #return datasets
    return all_items
