# -*- coding: utf-8 -*-
"""
:mod:`ecli_core` -- ECLI Core module
====================================

.. module:: ecli_core
   :synopsis: Core extension for ECLI, the EPICS command-line interface
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

"""

from __future__ import print_function
import logging
import os
import sys
import time
import functools
import threading

import epics

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import parse_argstring

# ECLI
import ecli_util as util
from ecli_plugin import ECLIPlugin
from ecli_util import (get_core_plugin)
from ecli_util import (AliasedPV, SimpleTable)
from ecli_util.decorators import ECLIExport
from ecli_util.magic_args import (ecli_magic_args, argument)

logger = logging.getLogger('ECLI.Core')


# Extension Initialization #
def load_ipython_extension(ipython):
    if ECLICore.instance is not None:
        print('ECLICore already loaded')
        return None

    logging.basicConfig()

    instance = ECLICore(shell=ipython, config=ipython.config)
    ECLICore.instance = instance

    util.__ipython__ = ipython
    util.export_magic_by_decorator(ipython, globals())
    util.export_class_magic(ipython, instance)
    return instance


def unload_ipython_extension(ipython):
    plugin = get_core_plugin()

    plugin._unregister_extensions()

    util.__ecli_core__ = None
    util.__ipython__ = None
    return True

# end Extension Initialization #


def shell_function_wrapper(exe_):
    """
    (decorator)
    Allows for shell commands to be directly added to IPython's
    user namespace
    """
    def wrapped(usermagics, args):
        cmd = '"%s" %s' % (exe_, args)
        logger.info('Executing: %s' % (cmd, ))

        shell = get_core_plugin().shell
        shell.system(cmd)

    return wrapped

# Plugin class #


class ECLICore(ECLIPlugin):
    VERSION = 1
    REQUIRES = []
    EXPORTS = {}
    instance = None

    CB_EXTENSION_LOADED = 'ExtensionLoaded'
    CB_EXTENSION_UNLOADED = 'ExtensionUnloaded'
    CB_EXIT = 'Exit'
    CB_CONFIG_LOADED = 'ConfigurationLoaded'
    core_callbacks = [CB_EXTENSION_LOADED, CB_EXTENSION_UNLOADED, CB_EXIT,
                      CB_CONFIG_LOADED,
                      ]

    shell = traitlets.Instance(
        'IPython.core.interactiveshell.InteractiveShellABC')
    use_catools = traitlets.Bool(False, config=True)
    catools_path = traitlets.Unicode(u'', config=True)
    ca_show_errors = traitlets.Bool(False, config=True)
    ca_logfile = traitlets.Unicode(u'', config=True)

    fields_columns = traitlets.List(traitlets.Unicode,
                                    default_value=[u'Field', u'Prompt', u'Pp'],
                                    config=True)
    fields_timeout = traitlets.Float(0.01, config=True)

    date_format = traitlets.Unicode(u'%y-%m-%d %I:%M:%S %p', config=True)

    # For conditional waits:
    monitor_verbosity = traitlets.Int(0, config=True)
    wait_timeout = traitlets.Float(0.25, config=True)

    # Timeout for determining record type
    type_timeout = traitlets.Float(0.5, config=True)

    # Aliases
    aliases = traitlets.Dict({'m1': 'IOC:m1',
                              'm2': 'IOC:m2',
                              's1': 'E1:Scaler:scaler1',
                              },
                             allow_none=False, config=False)
    enable_aliasing = traitlets.Bool(True, config=True)

    def __init__(self, shell, config):
        ECLICore.EXPORTS = {}

        util.__ecli_core__ = self

        self._cb_dict = {}
        for cb in self.core_callbacks:
            self.register_callback(cb)

        super(ECLICore, self).__init__(shell=shell, config=config)
        logger.info('Initializing ECLICore plugin')

        # To be flagged as configurable (and thus show up in %config), this
        # instance should be added to the shell's configurables list.
        if hasattr(shell, 'configurables'):
            shell.configurables.append(self)

        # Insert the exported functions into the user namespace (these will be
        # available on the command-line)
        for name, obj in self.EXPORTS.iteritems():
            shell.user_ns[name] = obj

        for trait in self.trait_names():
            try:
                change_fcn = getattr(self, '_%s_changed' % trait)
            except AttributeError:
                pass
            else:
                change_fcn(trait, None, getattr(self, trait))

        if epics.__version__ > '3.2.2':
            logger.debug('Using ECLI CA printf handler')
            self._ca_output = epics.ca.replace_printf_handler(self._ca_write)

        # ECLI extensions
        self._extensions = {self.__class__.__name__: self}
        self._callbacks = {}

        # Over-ride the exit request (TODO: custom shell might be a good idea?)
        self._shell_exit = self.shell.ask_exit
        self.shell.ask_exit = self.exit
        # atexit, shutdown_hook, etc did not work -- look into reasons?
        #  atexit - occurs after ipython shutdown

        self.shell._find_line_magic = self.shell.find_line_magic
        self.shell.find_line_magic = self._find_line_magic

    def _find_line_magic(self, magic_name, *args):
        """
        Normal IPython magic functions set 'self' to be the magic args instance,
        which is not very useful for ECLI plugins. Instead, this wraps that
        functionality, replacing the 'self' argument with the plugin instance.

        This works in conjunction with ecli_magic_args, which indicates the
        plugin class for the line magic.
        """
        fcn = self.shell._find_line_magic(magic_name, *args)
        if not hasattr(fcn, 'plugin_class'):
            return fcn

        @functools.wraps(fcn)
        def wrapped(arg):
            plugin = fcn.plugin_class.get_plugin()
            args = parse_argstring(fcn, arg)
            if args is not None:
                return fcn(plugin, args)

        return wrapped

    def get_extension(self, name):
        return self._extensions[name]

    def check_requirements(self, requirements):
        """
        Do a basic check on a list of extension requirements

        :param requirements: Each requirement should be in the format of a tuple:
            ('name', minimum_version)
        """
        ret = True
        for req in requirements:
            try:
                req, version = req
                req_str = '%s version >= %s' % (req, version)
            except:
                req_str = req

            if req not in self._extensions:
                logger.error('Required extension not loaded (%s)' %
                             (req_str, ))
                ret = False
            else:
                if self._extensions[req].VERSION < version:
                    err = 'Old version of required extension (requires %s)' % \
                          (req_str, )
                    logger.error(err)
                    ret = False

        return ret

    def register_extension(self, plugin_class, globals_=None, class_magic=True,
                           **kwargs):
        """
        Register an extension with ECLI

        :param plugin_class: The class of the extension/plugin
        :type plugin_class: class
        :param globals_: if specified, the global namespace will be checked for
                         magicargument/ECLIExport decorators, automatically exporting
                         those to the user namespace
        :type globals_: dict
        :param class_magic: if enabled, the class will be checked for magic args/
                            ECLIExport decorators
        :type class_magic: bool
        :param kwargs: passed to the plugin class initializer
        :type kwargs: dict
        """
        assert(ECLIPlugin in plugin_class.__bases__)

        name = plugin_class.__name__
        version = plugin_class.VERSION
        requires = plugin_class.REQUIRES

        if name in self._extensions:
            logger.error('Extension already loaded: %s' % (name, ))
            return None

        if not self.check_requirements(requires):
            logger.error('* Failed to load %s (version %s)' % (name, version))
            return None

        instance = plugin_class(shell=self.shell, config=self.shell.config,
                                **kwargs)

        # IPython did away with its plugin management system:
        #self.shell.plugin_manager.register_plugin(name, instance)

        if globals_ is not None:
            util.export_magic_by_decorator(self.shell, globals_)

        if class_magic:
            util.export_class_magic(self.shell, instance)

        self._extensions[name] = instance
        logger.info('* Extension %s loaded' % name)

        self.run_callback(self.CB_EXTENSION_LOADED, self.__class__.__name__,
                          ext_name=name)
        return instance

    def unregister_extension(self, name):
        '''
        Unregister an extension by name (remove its callbacks, etc.)
        '''
        if name in self._extensions:
            #self.shell.plugin_manager.unregister_plugin(name)

            del self._extensions[name]
            logger.info('* Extension %s unloaded' % name)

            self.run_callback(self.CB_EXTENSION_UNLOADED,
                              self.__class__.__name__, ext_name=name)

    def _unregister_extensions(self):
        '''
        Unregister all extensions
        '''
        for name in self._extensions.keys():
            if name != self.__class__.__name__:
                self.unregister_extension(name)

    def _get_catool_path(self, executable):
        return os.path.join(self.catools_path, executable)

    def set_variable(self, name, value):
        '''
        Set a variable in the user namespace (visible to user on the command
        line)
        '''
        self.shell.user_ns[name] = value

    def get_variable(self, name):
        '''
        Get a variable's value from the user namespace (visible to user
        on the command line)
        '''
        return self.shell.user_ns[name]

    def get_aliased_name(self, name):
        """
        Returns an aliased name if it exists
        (e.g., if PREFIX:PV is aliased to pv, it returns pv)
        """
        if isinstance(name, (list, tuple)):
            type_ = type(name)
            return type_(self.get_aliased_name(s) for s in name)

        rev = self.reversed_aliases
        if name in rev:
            return rev[name]
        else:
            return name

    def _aliases_changed(self, *args):
        # Update the reversed alias list
        # (note that python guarantees values()/keys() are in the same order,
        #  assuming no modifications have taken place)
        rev = dict(zip(self.aliases.values(), self.aliases.keys()))
        self._reversed_aliases = rev

    @property
    def reversed_aliases(self):
        if not self.enable_aliasing:
            return {}

        return self._reversed_aliases

    # -- catools --
    _catools = ('camonitor', 'caget', 'caput')

    def _wrap_catools(self):
        for catool in self._catools:
            path = os.path.join(self.catools_path, catool)
            self.shell.define_magic(catool, shell_function_wrapper(path))

    def _use_catools_changed(self, name='', old='', new_value=''):
        if self.use_catools:
            # this works, directly aliasing the pv tools, but doesn't allow for
            # alias expansion
            # alias_manager = self.shell.alias_manager
            # for tool in CATOOLS:
            #    if tool not in alias_manager:
            #        print('Adding alias for "%s"' % tool)
            #        alias_manager.define_alias(tool, tool)

            logger.info('Using command-line catools')
            self._wrap_catools()
        else:
            logger.info('Using Python-based catools')
            for catool in self._catools:
                function = globals()[catool]
                self.shell.define_magic(catool, function)

    def _catools_path_changed(self, name='', old='', new_value=''):
        if self.use_catools:
            self._wrap_catools()

    def _ca_logfile_changed(self, name='', old='', new_value=''):
        if self.ca_logfile:
            try:
                self._ca_logfile = open(self.ca_logfile, 'at')
            except Exception as ex:
                logger.error('Unable to open log file %s: (%s) %s' %
                             (self.ca_logfile, ex.__class__.__name__, ex))
                self._ca_logfile = None
        else:
            self._ca_logfile = None

    def _ca_write(self, msg):
        """
        Called when CA wants to print an exception, such as:
         CA.Client.Exception...............................................
             Warning: "Identical process variable names on multiple servers"
             Context: "Channel: "x", Connecting to: x:5064, Ignored: y:5064"
             Source File: ..\cac.cpp line 1297
             Current Time: Mon Jun 17 2000 10:22:30.002440862
         ..................................................................
        """
        msg = msg.rstrip()
        if self._ca_logfile is not None:
            try:
                print(msg, file=self._calogfile)
            except Exception as ex:
                logger.debug('ca error', ex)

        if self.ca_show_errors:
            print('(CA) %s' % msg)

        logger.debug('(CA) %s' % msg)

    def exit(self):
        """
        Called before the user exits IPython, notifying each registered
        plugin
        """
        logger.debug('Exiting')

        self.run_callback(self.CB_EXIT, self.__class__.__name__)

        for name, inst in self._extensions.iteritems():
            if inst is self:
                continue

            logger.debug('Plugin exit: %s' % name)
            try:
                inst.exit()
            except Exception as ex:
                print('Plugin %s exit failed: (%s) %s' %
                     (name, ex.__class__.__name__, ex))

                util.print_traceback(ex)

        self._shell_exit()

    def _save_config(self, filename, ignore=[u'shell', u'config']):
        """
        Save ECLI-related configuration to `filename`

        :param filename: filename to save to
        :param ignore: list of traits to ignore, by name
        """

        with open(filename, 'wt') as f:
            # TODO deal with overwriting old configuration files and unloaded
            # extensions, this whole thing not being very smart, etc.
            print('c = get_config()', file=f)

            for extension in self._extensions.values():
                ext_name = extension.__class__.__name__
                print('', file=f)
                print('# Extension: %s' % ext_name, file=f)

                if ext_name.startswith('ECLI') and hasattr(extension, '_trait_dict'):
                    for name, value in extension._trait_dict.items():
                        if name in ignore:
                            continue

                        name = '%s.%s' % (ext_name, name)
                        repr_ = repr(value)
                        # TODO ... ugh
                        if repr_.startswith('<'):
                            continue

                        print('c.%s = %s' % (name, repr_), file=f)

        logger.info('Wrote configuration to %s' % filename)

    def _load_ecli_config(self, filename):
        """
        Load ECLI-related configuration from `filename`

        :param filename: configuration filename
        """
        import IPython.config.loader as loader

        c = loader.PyFileConfigLoader(filename, )
        try:
            c.load_config()
        except Exception as ex:
            logger.error("Failed to load config file %s" % filename,
                         exc_info=True)
            # TODO can still load successfully parsed parts...
            return False

        for extension in self._extensions.values():
            ext_name = extension.__class__.__name__
            if ext_name in c.config:
                logger.debug('Updating configuration for %s' % ext_name)
                for name, value in c.config[ext_name].items():
                    try:
                        setattr(extension, name, value)
                    except Exception as ex:
                        logger.error('Failed %s.%s (%s) %s' %
                                     (ext_name, name,
                                      ex.__class__.__name__, ex))

                        logger.debug('Configuration file load failed %s.%s=%s' %
                                     (ext_name, name, value),
                                     ext_info=True)

        self.run_callback(self.CB_CONFIG_LOADED, self.__class__.__name__)
        return True


@ecli_magic_args(ECLICore)
@argument('filename', type=unicode, help='Configuration filename',
          nargs='?', default=u'ecli_config.py')
def save_config(margs, self, args):
    """
    Save ECLI-related configuration to `filename`.

    Output file should be readable by
    IPython.config.loader.PyFileConfigLoader
    """
    core = get_core_plugin()
    core._save_config(args.filename)


@ecli_magic_args(ECLICore)
@argument('filename', type=unicode, help='Configuration filename',
          nargs='?', default=u'ecli_config.py')
def load_config(margs, self, args):
    """
    Load ECLI-related configuration from `filename`.

    Input file should be readable by
    IPython.config.loader.PyFileConfigLoader
    """

    core = get_core_plugin()
    core._load_ecli_config(args.filename)


@ecli_magic_args(ECLICore)
@argument('pvs', type=AliasedPV, nargs='+', help='PV(s) to monitor')
def camonitor(mself, self, args):
    """
    $ monitor pv1 [[pv2] [pv3]...]
    Monitor until Ctrl-C is pressed
    """
    pvs = args.pvs
    print('Monitoring PVs:', ', '.join(pvs))

    def changed(pvname='', value='', timestamp='', **kwargs):
        print('%s\t%s\t%s' % (timestamp, pvname, value))

    try:
        for pv in pvs:
            epics.camonitor(pv, callback=changed)

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        logger.error('Monitor failed: (%s) %s' % (ex.__class__.__name__, ex))
    finally:
        for pv in pvs:
            epics.camonitor_clear(pv)


@ecli_magic_args(ECLICore)
@argument('pv', type=AliasedPV, nargs='+', help='PV(s) to get')
def caget(mself, self, args):
    """
    Get one or more PV's values over channel access
    """
    for pv in args.pv:
        try:
            print(pv, end='\t')
            print(epics.caget(pv))
        except KeyboardInterrupt:
            break
        except Exception as ex:
            print('caget failed: (%s) %s' % (ex.__class__.__name__, ex))


@ecli_magic_args(ECLICore)
@argument('pv', type=AliasedPV, help='PV to set')
@argument('value', type=str)
def caput(mself, self, args):
    """
    Put (set) a process variable's (PV) value over channel access
    """
    print('Old: ', args.pv, end='\t')
    print(epics.caget(args.pv))

    try:
        epics.caput(args.pv, args.value, wait=True)

        print('New: ', args.pv, end='\t')
        print(epics.caget(args.pv))
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        print('caput failed: (%s) %s' % (ex.__class__.__name__, ex))


@ECLIExport
def fields(pv, string):
    '''
    Search the field information database for 'text'. If the first
    argument is a PV it will detect its record type, otherwise use a
    record type (.RTYP) to start with.
    '''
    try:
        rf = util.get_record_fields(pv)
    except IOError:
        # not a record type, or not one we have information on
        # try it as a PV instead:
        rtype = util.get_record_type(pv)
        rf = util.get_record_fields(rtype)
    else:
        rtype = pv

    text = ' '.join(string)

    headers = ['Field'] + [col.capitalize() for col in rf.columns]
    table = SimpleTable(headers)
    rows = list([name] + info for name, info in rf.find(text))
    for row in rows:
        table.add_row(row)

    return rtype, table


@ecli_magic_args(ECLICore)
@argument('pv', type=AliasedPV, help='PV or record type')
@argument('string', nargs='+', type=str)
@argument('-v', '--values', action='store_const', const=True,
          help='Display current value of the field')
@argument('-a', '--all', action='store_const', const=True,
          help='Show all columns')
def _fields(magic_args, self, args):
    """
    $ fields [record_type/pv] [string] [--values]
    Examples:
        $ fields IOC:m1 value
        $ fields IOC:m1 user --values --all
        $ fields scaler time

    If -a is unspecified, %config ECLICore.fields_columns will determine
    the columns to display.
    """

    rtype, table = fields(args.pv, args.string)
    print('* Record type: %s' % rtype)
    print()

    core = get_core_plugin()
    if rtype != args.pv and args.values:
        # this means a PV was passed in and the RTYP was determined
        table.add_column('Value', index=1, fill='')
        for i, row in enumerate(table.rows):
            if i == 0:
                pass
            else:
                field = row[0]
                value = epics.caget('%s.%s' % (args.pv, field),
                                    connection_timeout=core.fields_timeout,
                                    verbose=False)
                if value is None:
                    value = ''

                table[1, i] = '%s' % value

    if not args.all:
        def check_col(col):
            return (col in show_fields or
                    col == u'Field' or col == u'Value')

        show_fields = core.fields_columns

        remove_columns = [i for i, col in enumerate(table.headers)
                          if not check_col(col)]

        table.remove_columns_by_index(remove_columns)

    table.print_(format_str=u'{:<%d}', delimiter=' | ')


@ECLIExport
def debug_trace(fn='trace.txt', trace_threads=False):
    import linecache

    def trace_lines(frame, event, arg):
        if event != 'line':
            return
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        if not ('cas' in filename or 'pv_manager' in filename):
            return

        with lock:
            print('  %s:%s [%d] %s' % (filename, func_name, line_no,
                                       linecache.getline(filename, line_no)),
                  file=f)

        f.flush()

    def trace_calls(frame, event, arg):
        if event != 'call':
            return

        co = frame.f_code
        func_name = co.co_name
        if func_name == 'write':
            return

        line_no = frame.f_lineno
        filename = co.co_filename
        print('[%s:%s] call %s' % (filename, line_no, func_name),
              file=f)

        f.flush()
        return trace_lines

    f = open(fn, 'wt')
    sys.settrace(trace_calls)

    if trace_threads:
        # TODO include thread id in filename/etc
        lock = threading.Lock()
        threading.settrace(trace_calls)

#debug_trace()
try:
    from gui_config import gui_config
except ImportError:
    pass
else:
    # Export the gui config functionality to the user
    gui_config = ECLIExport(gui_config)
