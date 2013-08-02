"""
:mod:`ecli_cas` -- ECLI Channel Access Server
=============================================

.. module:: ecli_cas
   :synopsis: ECLI channel access server (by way of pcaspy)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>

.. note:: Recommended `pcaspy`_ version >= 0.4.1

.. _pcaspy: http://code.google.com/p/pcaspy/

"""

import pcaspy

try:
    PCAS_TYPES = tuple(pcaspy.driver._ait_d.keys())
    PCAS_SEVERITY = [key for key in pcaspy.alarm.Severity.__dict__.keys()
                     if key.endswith('_ALARM')]
except:
    PCAS_TYPES = ('str', 'float', 'char', 'int')
    PCAS_SEVERITY = ('NO_ALARM', 'MINOR_ALARM', 'MAJOR_ALARM', 'INVALID_ALARM')


from ecli_util import ECLIError

# Exceptions for this extension
class CAPVBadValue(ECLIError):
    """
    Used for PV write callbacks -- raise this exception to reject
    the written value.
    """
    pass

from .pv_manager import (CAPV, CAServer, CADriver, PVManager, )
from .cas import (load_ipython_extension, unload_ipython_extension, ECLIcas)
