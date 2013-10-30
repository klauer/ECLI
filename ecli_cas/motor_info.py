#!/usr/bin/env python
"""
:mod:`ecli_cas.motor_info` -- Motor record information
======================================================

.. module:: ecli_cas.motor_info
   :synopsis: Fields and such related to the motor record
.. moduleauthor:: Ken Lauer <klauer@bnl.gov>
"""

from record_info import MENU_YESNO, MENU_ALARM_SEVR

# -- motor record --
POSITION_USER = 0
POSITION_DIAL = 1
POSITION_RAW = 2
POSITION_TYPES = [POSITION_USER, POSITION_DIAL, POSITION_RAW]

MENU_MOTOR_YESNO = ('No', 'Yes')
MOTOR_GO = 'SPMG'
MOTOR_GO_ENUM = ['Stop', 'Pause', 'Move', 'Go']
MOTOR_GO_DEFAULT = MOTOR_GO_ENUM.index('Go')
MOTOR_GO_GO = MOTOR_GO_ENUM.index('Go')

MOTOR_USER_HIGH_LIMIT = 'HLM'
MOTOR_USER_LOW_LIMIT = 'LLM'
MOTOR_USER_READBACK = 'RBV'
MOTOR_USER_VALUE = 'VAL'

MOTOR_DIAL_HIGH_LIMIT = 'DHLM'
MOTOR_DIAL_LOW_LIMIT = 'DLLM'
MOTOR_DIAL_READBACK = 'DRBV'
MOTOR_DIAL_VALUE = 'DVAL'

MOTOR_RAW_VALUE = 'RVAL'
MOTOR_RAW_READBACK = 'RRBV'

MOTOR_DIRECTION = 'DIR'
MOTOR_DIRECTION_ENUM = ['Pos', 'Neg']
MOTOR_DIRECTION_POS = MOTOR_DIRECTION_ENUM.index('Pos')
MOTOR_DIRECTION_NEG = MOTOR_DIRECTION_ENUM.index('Neg')
MOTOR_MOVE_DIRECTION = 'TDIR'

MOTOR_STATUS = 'MSTA'

MOTOR_TWEAK_VALUE = 'TWV'
MOTOR_TWEAK_REVERSE = 'TWR'
MOTOR_TWEAK_FORWARD = 'TWF'
MOTOR_DONE_MOVE = 'DMOV'
MOTOR_MOVING = 'MOVN'
MOTOR_OFFSET = 'OFF'

MOTOR_AT_HIGH_LIMIT = 'HLS'
MOTOR_AT_LOW_LIMIT = 'LLS'
MOTOR_LIMIT_VIOLATION = 'LVIO'

MOTOR_RES = 'MRES'
MOTOR_ENCODER_RES = 'ERES'
MOTOR_RES_DEFAULT = 1e-8
MOTOR_RES_MIN = 1e-12
MOTOR_RES_MAX = 1

FIELD_INFO_ALIAS = 0
FIELD_INFO_TYPE = 1
FIELD_INFO_DEFAULTS = 2

MOTOR_ASYN_FIELDS = ('VAL', 'DVAL', 'RVAL', '', 'TWF', 'TWR')
MOTOR_FIELDS = {
    # field               :  alias                     , type   ,            (default, min, max)
    MOTOR_DONE_MOVE       : ['done_move'               , 'short',            (    0,     0,   0)],
    MOTOR_OFFSET          : ['offset'                  , 'float',            (    0,     0,   0)],
    MOTOR_TWEAK_FORWARD   : ['tweak_forward'           , 'short',            (    0,     0,   0)],

    MOTOR_USER_VALUE      : ['user_value'              , 'float',            (    0,     0,   0)],
    MOTOR_USER_READBACK   : ['user_readback'           , 'float',            (    0,     0,   0)],
    MOTOR_USER_LOW_LIMIT  : ['user_low_limit'          , 'float',            (    0,     0,   0)],
    MOTOR_USER_HIGH_LIMIT : ['user_high_limit'         , 'float',            (   10,     0,   0)],

    MOTOR_DIAL_VALUE      : ['dial_value'              , 'float',            (    0,     0,   0)],
    MOTOR_DIAL_LOW_LIMIT  : ['dial_low_limit'          , 'float',            (    0,     0,   0)],
    MOTOR_DIAL_HIGH_LIMIT : ['dial_high_limit'         , 'float',            (   10,     0,   0)],
    MOTOR_AT_HIGH_LIMIT   : ['at_high_limit_switch'    , 'short',            (    0,    0,    0)],
    MOTOR_AT_LOW_LIMIT    : ['at_low_limit_switch'     , 'short',            (    0,    0,    0)],

    MOTOR_RAW_VALUE       : ['raw_value'               , 'float',            (    0,     0,   0)],
    MOTOR_RAW_READBACK    : ['raw_readback'            , 'float',            (    0,     0,   0)],

    MOTOR_ENCODER_RES     : ['encoder_res'             , 'int'  ,            (1e-08, 1e-12,   1)],
    MOTOR_TWEAK_REVERSE   : ['tweak_reverse'           , 'int'  ,            (    0,     0,   0)],
    MOTOR_TWEAK_VALUE     : ['tweak_value'             , 'float',            (    1,     0,   0)],
    MOTOR_MOVE_DIRECTION  : ['move_direction'          , 'int'  ,            (    0,     0,   0)],
    MOTOR_RES             : ['motor_res'               , 'int'  ,            (1e-08, 1e-12,   1)],
    MOTOR_STATUS          : ['status'                  , 'float',            (    0,     0,   0)],

    MOTOR_LIMIT_VIOLATION : ['limit_violation'         , 'short',            (    0,    0,    0)],

    MOTOR_GO              : ['go'                      , 'enum' ,   (MOTOR_GO_DEFAULT, MOTOR_GO_ENUM)],
    MOTOR_DIRECTION       : ['direction'               , 'enum' ,   (0, MOTOR_DIRECTION_ENUM)],
    }

# automatically generated fields from the docs
other_fields = {
    'ACCL'   : ['seconds_to_velocity'     , 'float',   (    0,    0,    0)],
    'ADEL'   : ['archive_deadband'        , 'float',   (    0,    0,    0)],
    'ALST'   : ['last_valve_archived'     , 'float',   (    0,    0,    0)],
    'ATHM'   : ['at_home'                 , 'short',   (    0,    0,    0)],
    'BACC'   : ['bl_seconds_to_veloc'     , 'float',   (    0,    0,    0)],
    'BDST'   : ['bl_distance'             , 'float',   (    0,    0,    0)],
    'BVEL'   : ['bl_velocity_egu_s'       , 'float',   (    0,    0,    0)],
    'CARD'   : ['card_number'             , 'short',   (    0,    0,    0)],
    'CDIR'   : ['raw_commanded_direction' , 'short',   (    0,    0,    0)],
    'CNEN'   : ['enable_control'          , 'enum',    (0, ('Disable', 'Enable'))],
    'DCOF'   : ['derivative_gain'         , 'float',   (    0,    0,    0)],
    'DHLM'   : ['dial_high_limit'         , 'float',   (    0,    0,    0)],
    'DIFF'   : ['difference_dial'         , 'float',   (    0,    0,    0)],
    'DIR'    : ['user_direction'          , 'enum',    (0, ('Pos', 'Neg'))],
    'DLLM'   : ['dial_low_limit'          , 'float',   (    0,    0,    0)],
    'DLY'    : ['readback_settle_time_s'  , 'float',   (    0,    0,    0)],
    'DMOV'   : ['done_moving_to_value'    , 'short',   (    0,    0,    0)],
    'DRBV'   : ['dial_readback_value'     , 'float',   (    0,    0,    0)],
    'DVAL'   : ['dial_value'              , 'float',   (    0,    0,    0)],
    'EGU'    : ['engineering_units'       , 'str',     (   '',    0,    0)],
    'ERES'   : ['encoder_res'             , 'float',   (    0,    0,    0)],
    'FOF'    : ['freeze_offset'           , 'short',   (    0,    0,    0)],
    'FOFF'   : ['offset_freeze_switch'    , 'enum',    (0, ('Variable', 'Frozen'))],
    'FRAC'   : ['move_fraction'           , 'float',   (    0,    0,    0)],
    'HHSV'   : ['hihi_severity'           , 'enum',    (0, MENU_ALARM_SEVR)],
    'HIGH'   : ['high_alarm_limit'        , 'float',   (    0,    0,    0)],
    'HIHI'   : ['hihi_alarm_limit'        , 'float',   (    0,    0,    0)],
    'HLM'    : ['user_high_limit'         , 'float',   (    0,    0,    0)],
    'HLSV'   : ['hw_lim_violation_svr'    , 'enum',    (0, MENU_ALARM_SEVR)],
    'HOMF'   : ['home_forward'            , 'short',   (    0,    0,    0)],
    'HOMR'   : ['home_reverse'            , 'short',   (    0,    0,    0)],
    'HOPR'   : ['high_operating_range'    , 'float',   (    0,    0,    0)],
    'HSV'    : ['high_severity'           , 'enum',    (0, MENU_ALARM_SEVR)],
    'HVEL'   : ['home_velocity'           , 'float',   (    0,    0,    0)],
    'ICOF'   : ['integral_gain'           , 'float',   (    0,    0,    0)],
    'INIT'   : ['startup_commands'        , 'str',     (   '',    0,    0)],
    'JAR'    : ['jog_acceleration_egu_s2' , 'float',   (    0,    0,    0)],
    'JOGF'   : ['jog_motor_forward'       , 'short',   (    0,    0,    0)],
    'JOGR'   : ['jog_motor_reverse'       , 'short',   (    0,    0,    0)],
    'JVEL'   : ['jog_velocity'            , 'float',   (    0,    0,    0)],
    'LDVL'   : ['last_dial_des_val'       , 'float',   (    0,    0,    0)],
    'LLM'    : ['user_low_limit'          , 'float',   (    0,    0,    0)],
    'LLSV'   : ['lolo_severity'           , 'enum',    (0, MENU_ALARM_SEVR)],
    'LOCK'   : ['soft_channel_pos_lock'   , 'enum',    (0, MENU_YESNO)],
    'LOLO'   : ['lolo_alarm_limit'        , 'float',   (    0,    0,    0)],
    'LOPR'   : ['low_operating_range'     , 'float',   (    0,    0,    0)],
    'LOW'    : ['low_alarm_limit'         , 'float',   (    0,    0,    0)],
    'LRLV'   : ['lastrel_value'           , 'float',   (    0,    0,    0)],
    'LRVL'   : ['lastraw_des_val'         , 'float',   (    0,    0,    0)],
    'LSPG'   : ['last_spmg'               , 'enum',    (0, ('Stop', 'Pause', 'Move', 'Go'))],
    'LSV'    : ['low_severity'            , 'enum',    (0, MENU_ALARM_SEVR)],
    'LVAL'   : ['last_user_des_val'       , 'float',   (    0,    0,    0)],
    'MDEL'   : ['monitor_deadband'        , 'float',   (    0,    0,    0)],
    'MLST'   : ['last_valve_monitored'    , 'float',   (    0,    0,    0)],
    'MIP'    : ['motion_in_progress'      , 'short',   (    0,    0,    0)],
    'MISS'   : ['ran_out_of_retries'      , 'short',   (    0,    0,    0)],
    'MMAP'   : ['monitor_mask'            , 'ulong',   (    0,    0,    0)],
    'MOVN'   : ['motor_is_moving'         , 'short',   (    0,    0,    0)],
    'MRES'   : ['motor_res'               , 'float',   (    0,    0,    0)],
    'MSTA'   : ['motor_status'            , 'ulong',   (    0,    0,    0)],
    'NMAP'   : ['monitor_mask'            , 'ulong',   (    0,    0,    0)],
    'NTM'    : ['new_target_monitor'      , 'enum',    (0, MENU_YESNO)],
    'NTMF'   : ['new_tgt_monitor_dbdband' , 'short',   (    0,    0,    0)],
    'OFF'    : ['user_offset'             , 'float',   (    0,    0,    0)],
    'OMSL'   : ['output_mode_select'      , 'enum',    (0, ('supervisory', 'closed_loop'))],
    'PCOF'   : ['proportional_gain'       , 'float',   (    0,    0,    0)],
    'PERL'   : ['periodic_limits'         , 'enum',    (0, MENU_YESNO)],
    'POST'   : ['post_move_commands'      , 'str',     (   '',    0,    0)],
    'PP'     : ['post_process_command'    , 'short',   (    0,    0,    0)],
    'PREC'   : ['display_precision'       , 'short',   (    0,    0,    0)],
    'PREM'   : ['pre_move_commands'       , 'str',     (   '',    0,    0)],
    'RBV'    : ['user_readback_value'     , 'float',   (    0,    0,    0)],
    'RCNT'   : ['retry_count'             , 'short',   (    0,    0,    0)],
    'RDBD'   : ['retry_deadband'          , 'float',   (    0,    0,    0)],
    'RDIF'   : ['difference_raw'          , 'long',    (    0,    0,    0)],
    'RHLS'   : ['raw_high_limit_switch'   , 'short',   (    0,    0,    0)],
    'RLLS'   : ['raw_low_limit_switch'    , 'short',   (    0,    0,    0)],
    'RLV'    : ['relative_value'          , 'float',   (    0,    0,    0)],
    'RMOD'   : ['retry_mode'              , 'enum',    (0, ('Unity', 'Arthmetic', 'Geometric'))],
    'REP'    : ['raw_encoder_position'    , 'float',   (    0,    0,    0)],
    'RMP'    : ['raw_motor_position'      , 'float',   (    0,    0,    0)],
    'RRBV'   : ['raw_readback_value'      , 'float',   (    0,    0,    0)],
    'RRES'   : ['readback_step_size'      , 'float',   (    0,    0,    0)],
    'RTRY'   : ['max_retry_count'         , 'short',   (    0,    0,    0)],
    'RVAL'   : ['raw_value'               , 'float',   (    0,    0,    0)],
    'RVEL'   : ['raw_velocity'            , 'long',    (    0,    0,    0)],
    'S'      : ['speed_rps'               , 'float',   (    0,    0,    0)],
    'SBAK'   : ['bl_speed_rps'            , 'float',   (    0,    0,    0)],
    'SBAS'   : ['base_speed_rps'          , 'float',   (    0,    0,    0)],
    'SET'    : ['set_use_switch'          , 'enum',    (0, ('Use', 'Set'))],
    'SMAX'   : ['max_velocity_rps'        , 'float',   (    0,    0,    0)],
    'SPMG'   : ['stop_pause_move_go'      , 'enum',    (0, ('Stop', 'Pause', 'Move', 'Go'))],
    'SREV'   : ['steps_per_revolution'    , 'long',    (    0,    0,    0)],
    'SSET'   : ['set_set_mode'            , 'short',   (    0,    0,    0)],
    'STOP'   : ['stop'                    , 'short',   (    0,    0,    0)],
    'STUP'   : ['status_update_request'   , 'enum',    (0, ('OFF', 'ON', 'BUSY'))],
    'SUSE'   : ['set_use_mode'            , 'short',   (    0,    0,    0)],
    'SYNC'   : ['sync_positions'          , 'enum',    (0, MENU_MOTOR_YESNO)],
    'TDIR'   : ['direction_of_travel'     , 'short',   (    0,    0,    0)],
    'TWF'    : ['tweak_forward'           , 'short',   (    0,    0,    0)],
    'TWR'    : ['tweak_reverse'           , 'short',   (    0,    0,    0)],
    'TWV'    : ['tweak_size'              , 'float',   (    0,    0,    0)],
    'UEIP'   : ['use_encoder_if_present'  , 'enum',    (0, MENU_MOTOR_YESNO)],
    'UREV'   : ['egu_per_revolution'      , 'float',   (    0,    0,    0)],
    'URIP'   : ['use_rdbl_link_if_present', 'enum',    (0, MENU_MOTOR_YESNO)],
    'VAL'    : ['user_value'              , 'float',   (    0,    0,    0)],
    'VBAS'   : ['base_velocity'           , 'float',   (    0,    0,    0)],
    'VELO'   : ['velocity'                , 'float',   (    0,    0,    0)],
    'VERS'   : ['code_version'            , 'float',   (    0,    0,    0)],
    'VMAX'   : ['max_velocity'            , 'float',   (    0,    0,    0)],
    'VOF'    : ['variable_offset'         , 'short',   (    0,    0,    0)],
# no links
}


def get_field_defaults(field):
    return MOTOR_FIELDS[field][FIELD_INFO_DEFAULTS]


for k, v in other_fields.iteritems():
    if k not in MOTOR_FIELDS:
        MOTOR_FIELDS[k] = v

del other_fields
