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

        if not hasattr(self, '_cb_dict'):
            self._cb_dict = dict()

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

        self.core.add_callback(self.core.CB_CONFIG_LOADED, self.config_loaded)

    def config_loaded(self, **kwargs):
        pass

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
            self.register_callback(cb)

    def _unregister_callbacks(self):
        for cb in self._callbacks:
            self.unregister_callback(cb)

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

    def register_callback(self, name):
        """
        Define a callback for an extension, allowing other extensions
        to be notified when it is triggered
        """
        self._cb_dict[name] = []

        self.logger.debug('Callback registered: %s' % name)

    def unregister_callback(self, name):
        """
        Unregister a previously defined callback
        """
        self._callbacks.remove(name)
        del self._cb_dict[name]

        self.logger.debug('Callback unregistered: %s' % name)

    def add_callback(self, name, fcn):
        """
        Calls `fcn` when the named callback is triggered
        """
        try:
            cb_list = self._cb_dict[name]
        except KeyError:
            raise ValueError('Callback does not exist: %s' % name)
        else:
            if fcn not in cb_list:
                cb_list.append(fcn)

    def run_callback(self, name, handle_exceptions=True, show_traceback=None,
                     **kwargs):
        """
        Trigger a previously registered callback

        :param name: The callback name
        :param handle_exceptions: Catch exceptions and continue processing other
                                  callbacks
        :param show_traceback: A file-like object indicating where to print the
                               traceback to (or None to disable)
        :param kwargs: Keyword arguments to be passed to the callback functions
        """
        for fcn in self._cb_dict[name]:
            try:
                fcn(**kwargs)
            except Exception as ex:
                if handle_exceptions:
                    self.logger.debug('Callback %s failed' % (name, ),
                                      exc_info=(show_traceback is not None))
                    if show_traceback is not None:
                        print('Callback %s failed' % (name, ))
                        util.print_traceback(ex, f=show_traceback)

                else:
                    raise
