# -*- coding: utf-8 -*-
# vi:sw=4 ts=4
"""
:mod:`ecli_template` -- ECLI extension template
===============================================

.. module:: ecli_template
   :synopsis: DESCRIPTION
.. moduleauthor:: x <y@z>
"""
from __future__ import print_function
import os
import sys
import time
import logging

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.error import UsageError

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util import (ECLIError, ECLIExport)
from ecli_util.magic_args import (ecli_magic_args, argument)

logger = logging.getLogger('ECLI.Template')


# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLITemplate, logger=logger, globals_=globals())


def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLITemplate)


class ECLITemplate(ECLIPlugin):
    """
    DESCRIPTION
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1)]
    EXPORTS = {}  # see __init__

    _callbacks = []
    param = traitlets.List(traitlets.Unicode,
                           default_value=('m1', 'm2'),
                           config=True)
    param2 = traitlets.Int(8, config=True)

    def __init__(self, shell, config):
        # ECLITemplate.EXPORTS = {}

        super(ECLITemplate, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLITemplate')

    def _param_changed(self, *args):
        pass

    @property
    def logger(self):
        return logger

    @ECLIExport
    def export_function(self):
        """
        This function will be easily accessible by the user if this
        plugin is loaded.

        @ECLIExport functions can also be defined outside of this class.
        """
        pass


@ecli_magic_args(ECLITemplate)
@argument('pv', type=AliasedPV, nargs='+',
          help='PV')
def command(margs, self, args):
    """
    $ command pv

    Desc
    """
    # margs is the magic arguments instance
    # self is the instance of your plugin class
    # args is the pre-parsed argparse Namespace:
    #   for %command pv_name
    #   args.pv would be equal to "pv_name"
    pass
