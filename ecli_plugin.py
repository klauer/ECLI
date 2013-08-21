# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_plugin` -- ECLI plugin base
======================================

.. module:: ecli_plugin
   :synopsis: Plugin base for ECLI extensions/plugins
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

from __future__ import print_function
import sys
import logging

from IPython.config.configurable import Configurable
import IPython.utils.traitlets as traitlets

from ecli_util import (get_plugin, get_core_plugin)
import ecli_util as util

# Extension Initialization #


def load_ipython_extension(ipython):
    raise NotImplementedError('Base class')

def unload_ipython_extension(ipython):
    raise NotImplementedError('Base class')

# end Extension Initialization #

# Plugin class #
class ECLIPlugin(Configurable):
    VERSION = 1
    REQUIRES = []
    EXPORTS = {}
    _callbacks = []
    shell = traitlets.Instance(
        'IPython.core.interactiveshell.InteractiveShellABC')

    def __init__(self, shell, config, init_traits=True):
        super(ECLIPlugin, self).__init__(shell=shell, config=config)

        # To be flagged as configurable (and thus show up in %config), this instance
        # should be added to the shell's configurables list.
        if hasattr(shell, 'configurables'):
            shell.configurables.append(self)

        # Insert the exported objects into the user namespace (these will be available
        # on the command-line)
        for name, obj in self.EXPORTS.iteritems():
            shell.user_ns[name] = obj

        self.core = get_core_plugin()
        if init_traits:
            self.update_all_traits()

    def update_all_traits(self):
        for trait in self.trait_names():
            try:
                change_fcn = getattr(self, '_%s_changed' % trait)
            except AttributeError:
                pass
            else:
                try:
                    change_fcn(trait, None, getattr(self, trait))
                except Exception as ex:
                    cname = self.__class__.__name__
                    exname = ex.__class__.__name__
                    self.logger.error('trait %s.%s (%s) %s' %
                                      (cname, trait, exname, ex), exc_info=True)
                    util.log_exception()

    @property
    def logger(self):
        """
        Override to use a non-root logger
        """
        return logging

    def _register_callbacks(self):
        for cb in self._callbacks:
            self.core.register_callback(cb, extension=self.__class__.__name__)

    def register_callback(self, name):
        self.core.register_callback(name, extension=self.__class__.__name__)

    def unregister_callback(self, name):
        self.core.unregister_callback(name, extension=self.__class__.__name__)

    def add_callback(self, name, fcn, extension='ECLICore'):
        self.core.add_callback(name, fcn, extension)

    def run_callback(self, cb_name, **kwargs):
        if 'extension' in kwargs:
            self.core.run_callback(cb_name, **kwargs)
        else:
            self.core.run_callback(cb_name, extension=self.__class__.__name__,
                                   **kwargs)

    def exit(self):
        pass

    @property
    def _trait_dict(self):
        ret = {}
        for name, value in self.traits().items():
            ret[name] = getattr(self, name)

        return ret

    @classmethod
    def get_plugin(cls):
        return get_plugin(cls.__name__)
