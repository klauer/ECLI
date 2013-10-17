#!/usr/bin/env python
"""
:mod:`ecli_cas.motor_info` -- Motor record information
======================================================

.. module:: ecli_cas.motor_info
   :synopsis: Fields and such related to all records
              (Basic record fields/menus; links/noaccess not included)
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""

# -- record basics --
MENU_PRIORITY = ('LOW', 'MEDIUM', 'HIGH')
MENU_YESNO = ('NO', 'YES')
MENU_ALARM_SEVR = ("NO_ALARM", "MINOR", "MAJOR", "INVALID")

MENU_RECORD_SCAN = ("Passive",
                    "Event",
                    "I/O Intr",
                    "10 second",
                    "5 second",
                    "2 second",
                    "1 second",
                    ".5 second",
                    ".2 second",
                    ".1 second",
                    )

MENU_ALARM_STAT = ("NO_ALARM",
                   "READ",
                   "WRITE",
                   "HIHI",
                   "HIGH",
                   "LOLO",
                   "LOW",
                   "STATE",
                   "COS",
                   "COMM",
                   "TIMEOUT",
                   "HWLIMIT",
                   "CALC",
                   "SCAN",
                   "LINK",
                   "SOFT",
                   "BAD_SUB",
                   "UDF",
                   "DISABLE",
                   "SIMM",
                   "READ_ACCESS",
                   "WRITE_ACCESS",
                   )

RECORD_FIELDS = {
    'NAME'                : ['name'                    , 'str'   ,           (   '',   '',   '')],
    'DESC'                : ['description'             , 'str'   ,           (   '',   '',   '')],
    'RTYP'                : ['record_type'             , 'str'   ,           (   '',   '',   '')],
    'DTYP'                : ['data_type'               , 'str'   ,           (   '',   '',   '')],
    'ASG'                 : ['access_security_group'   , 'str'   ,           (   '',   '',   '')],
    'TSE'                 : ['time_stamp_event'        , 'short' ,           (    0,    0,    0)],
    'DISP'                : ['disable_put_fields'      , 'uchar' ,           (    0,    0,    0)],
    'PUTF'                : ['db_put_field_process'    , 'uchar' ,           (    0,    0,    0)],
    'RPRO'                : ['reprocess'               , 'uchar' ,           (    0,    0,    0)],

    'STAT'                : ['current_alarm_status'    , 'enum'  ,           (0, MENU_ALARM_STAT)],
    'SEVR'                : ['current_alarm_severity'  , 'enum'  ,           (0, MENU_ALARM_SEVR)],
   #'NSTA'                : ['new_alarm_status'        , 'enum'  ,           (0, MENU_ALARM_STAT)],
   #'NSEV'                : ['new_alarm_severity'      , 'enum'  ,           (0, MENU_ALARM_SEVR)],
    'ACKS'                : ['alarm_ack_severity'      , 'enum'  ,           (0, MENU_ALARM_SEVR)],
    'ACKT'                : ['alarm_ack_transient'     , 'enum'  ,           (0, MENU_ALARM_SEVR)],
    'UDF'                 : ['undefined'               , 'uchar' ,           (    0,    0,    0)],

    'SCAN'                : ['scanning_rate'           , 'enum'  ,           (0, MENU_RECORD_SCAN)],
    'PINI'                : ['process_at_init'         , 'enum'  ,           (0, MENU_YESNO)],
    'PHAS'                : ['scan_phase_number'       , 'short' ,           (    0,    0,    0)],
    'EVNT'                : ['event_number'            , 'short' ,           (    0,    0,    0)],
    'PRIO'                : ['priority'                , 'enum'  ,           (0, MENU_PRIORITY)],
    'DISV'                : ['disable_value'           , 'short' ,           (    1,    0,    0)],
    'DISA'                : ['scan_disable_input_link_value' , 'short' ,     (    0,    0,    0)],
    'PROC'                : ['process'                 , 'uchar' ,           (    0,    0,    0)],
    'DISS'                : ['disable_alarm_severity'  , 'enum'  ,           (0, MENU_ALARM_SEVR)],
    'LCNT'                : ['lock_count'              , 'uchar' ,           (    0,    0,    0)],
    'PACT'                : ['processing_active'       , 'uchar' ,           (    0,    0,    0)],
   #'SDIS'                : ['scan_disable_input_link' , 'link'  ,
   #'FLNK'                : ['forward_link'            , 'link  ',           (),
   #'TSEL'                : ['time_stamp_event_link'   , 'link  ',           (),

   #'LSET'                : ['lock_set'                , noaccess
   #'SPVT'                : ['scan_private'            , 'noaccess' ,           (    0,    0,    0)],
}


