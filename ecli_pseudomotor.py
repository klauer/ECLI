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
import os
import sys
import time
import logging

# IPython
import IPython.utils.traitlets as traitlets
from IPython.core.magic_arguments import (argument, magic_arguments,
                                          parse_argstring)
from IPython.core.error import UsageError

# ECLI
from ecli_core import AliasedPV
from ecli_plugin import ECLIPlugin
import ecli_util as util
from ecli_util import (get_plugin, get_core_plugin)
from ecli_util import ECLIError
from ecli_util.decorators import ECLIExport

logger = logging.getLogger('ECLIPseudomotor')

# Loading of this extension
def load_ipython_extension(ipython):
    return util.generic_load_ext(ipython, ECLIPseudomotor, logger=logger, globals_=globals())

def unload_ipython_extension(ipython):
    return util.generic_unload_ext(ipython, ECLIPseudomotor)


class ECLIPseudomotor(ECLIPlugin):
    """
    DESCRIPTION
    """
    VERSION = 1
    REQUIRES = [('ECLICore', 1), ('ECLIcas', 1)]
    EXPORTS = {}

    _callbacks = []
    param = traitlets.List(traitlets.Unicode,
                           default_value=('m1', 'm2'),
                           config=True)
    param2 = traitlets.Int(8, config=True)

    def __init__(self, shell, config):
        super(ECLIPseudomotor, self).__init__(shell=shell, config=config)
        logger.debug('Initializing ECLI plugin ECLIPseudomotor')

    @staticmethod
    def get_plugin():
        return get_plugin('ECLIPseudomotor')

    def _param_changed(self, *args):
        pass

    @property
    def logger(self):
        return logger


@ECLIExport
def export_function():
    pass


@magic_arguments()
@argument('pv', type=AliasedPV, nargs='+',
          help='PV')
def command(self, arg):
    """
    $ command pv

    Desc
    """
    args = parse_argstring(command, arg)
    if args is None:
        return
