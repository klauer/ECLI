# vi:sw=4 ts=4
"""
Supporting functions for ecli_splot extension
"""

import shlex

SCAN_COMMAND_INFO = {'ascan': {'dim': 1, 'absolute': True,  'motors': 1},
                     'dscan': {'dim': 1, 'absolute': False,  'motors': 1},
                     'lup': {'dim': 1, 'absolute': False,  'motors': 1},
                     'a2scan': {'dim': 1, 'absolute': True,  'motors': 2},
                     'd2scan': {'dim': 1, 'absolute': False,  'motors': 2},
                     'a3scan': {'dim': 1, 'absolute': True,  'motors': 3},
                     'd3scan': {'dim': 1, 'absolute': False,  'motors': 3},

                     'mesh': {'dim': 2, 'absolute': True,  'motors': 2},
                     'amesh': {'dim': 2, 'absolute': True,  'motors': 2},
                     'dmesh': {'dim': 2, 'absolute': False,  'motors': 2},

                     # Custom ones
                     'spiral': {'dim': 1, 'absolute': False,  'motors': 2, 'custom': True},
                     'fermat': {'dim': 1, 'absolute': False,  'motors': 2, 'custom': True},
                     }


def parse_custom_scan(command):
    if '  ' in command:
        command = command.replace('  ', ' ')

    args = shlex.split(command, '#')
    if args[0].lower() not in SCAN_COMMAND_INFO:
        raise ValueError('Unknown scan command: %s' % args[0].lower())

    scan_command = args[0].lower()
    scan = SCAN_COMMAND_INFO[scan_command]

    if not scan.get('custom', False):
        return parse_scan_command(command)

    if scan_command == 'spiral':
        motors = args[1:3]
        absolute = False
        dim = 1
        spec_cmd = command
        x_range = float(args[3])
        y_range = float(args[4])
        dr_um = float(args[5])
        nth = int(args[6])
        wtime = float(args[7])
        data_points = int(args[8])
        motor_info = [(m, 0.0, 0.0, data_points) for m in motors]
        return {'motors': motor_info,
                'time': wtime,
                'absolute': absolute,
                'dimension': dim,
                'spec_cmd': spec_cmd,
                'info': (x_range, y_range, dr_um, nth, wtime),
                }

    elif scan_command == 'fermat':
        motors = args[1:3]
        absolute = False
        dim = 1
        spec_cmd = command
        x_range = float(args[3])
        y_range = float(args[4])
        dr_um = float(args[5])
        factor = float(args[6])
        wtime = float(args[7])
        motor_info = [(m, 0.0, 0.0, 0.0) for m in motors]
        return {'motors': motor_info,
                'time': wtime,
                'absolute': absolute,
                'dimension': dim,
                'spec_cmd': spec_cmd,
                'info': (x_range, y_range, dr_um, factor, wtime),
                }

    elif scan_command == 'timescan':
        wtime = float(args[1])
        sleep_time = float(args[2])
        return {'motors': [],
                'time': wtime,
                'absolute': True,
                'dimension': (1, ),
                'spec_cmd': command,
                'info': (sleep_time, )
                }

    else:
        raise ValueError('Unknown scan command: %s' % scan_command)


def parse_scan_command(command):
    if '  ' in command:
        command = command.replace('  ', ' ')

    args = shlex.split(command, '#')
    if args[0].lower() not in SCAN_COMMAND_INFO:
        raise ValueError('Unknown scan command: %s' % args[0].lower())

    scan_command = args[0].lower()
    scan = SCAN_COMMAND_INFO[scan_command]

    if scan.get('custom', False):
        return parse_custom_scan(command)

    args = args[1:]

    dim, nmotors, absolute = scan['dim'], scan['motors'], scan['absolute']
    if dim == 1:
        # 1D scans:
        #    motor, start, end
        #    and finally points, time => 3 * nmotors + 2
        motor_parms = 3
        expected_params = motor_parms * nmotors + 2
    elif dim == 2:
        # 2D scans:
        #    motor, start, end, points
        #    and finally time => 4 * nmotors + 1
        motor_parms = 4
        expected_params = motor_parms * nmotors + 1

    if len(args) != expected_params:
        raise ValueError('Invalid parameters to scan (expected: %d got: %d)' %
                         (expected_params, len(args)))

    motors, starts, ends = args[::motor_parms], args[1::motor_parms], args[2::motor_parms]
    other_args = args[motor_parms * nmotors:]
    other_args = args[motor_parms * nmotors:]

    if motor_parms == 3:
        data_points, wtime = other_args[:2]
        data_points = [int(data_points)]
        wtime = float(wtime)
    else:
        data_points = args[3::motor_parms]
        wtime = float(other_args[0])

    # TODO: does this belong still?
    motors = motors[:nmotors]
    if len(data_points) < nmotors:
        data_points.extend([data_points[-1]] * (nmotors - len(data_points)))

    motor_info = zip(motors, starts, ends, data_points)
    motor_info = [(motor, float(start), float(end), int(point))
                  for motor, start, end, point in motor_info]

    if dim == 1:
        # Note the double spaces between all motors
        motor_str = '  '.join('%s %g %g' % motor[:3] for motor in motor_info)
        spec_cmd = '%s  %s  %d %g' % (scan_command, motor_str, data_points[0], wtime)
    else:
        motor_str = '  '.join('%s %g %g %d' % motor for motor in motor_info)
        spec_cmd = '%s  %s  %g' % (scan_command, motor_str, wtime)

    return {'motors': motor_info,
            'time': wtime,
            'absolute': absolute,
            'dimension': dim,
            'spec_cmd': spec_cmd,
            }


def find_scan_command_by_dimension(dim, absolute, motors=None):
    for cmd, info in SCAN_COMMAND_INFO.iteritems():
        if info['dim'] == dim and absolute == info['absolute']:
            if motors is not None and info['motors'] == motors:
                return cmd
            elif motors is None:
                return cmd

    return None


def build_scan_command(motor_info, absolute=True, wtime=1.0, dim=None):
    """
    The first parameter should be a sequence of tuples:
        (motor_name, start pos, end pos, data points)

    For 1d scans (ascan, d2scan, etc.) the first motor must have data
    points specified -- the rest will be ignored.
    """
    motor_count = len(motor_info)
    if dim is None:
        dim = motor_count

    if dim <= 0:
        raise ValueError('Invalid dimension')

    scan_command = find_scan_command_by_dimension(dim, absolute, motor_count)
    if dim == 1:
        # Note the double spaces between all motors
        motor_str = '  '.join('%s %g %g' % tuple(motor[:3]) for motor in motor_info)
        return '%s  %s  %d %g' % (scan_command, motor_str, motor_info[0][-1], wtime)
    else:
        motor_str = '  '.join('%s %g %g %d' % tuple(motor) for motor in motor_info)
        return '%s  %s  %g' % (scan_command, motor_str, wtime)


def fix_scan_command(command):
    try:
        parsed = parse_scan_command(command)
    except ValueError:
        return command
    else:
        return parsed['spec_cmd']


READBACK_SUFFIXES = ['.RBV', '(actual)']


def readback_pvs(pv):
    pv = strip_readback_suffix(pv)
    return ['%s%s' % (pv, suffix) for suffix in READBACK_SUFFIXES]


def strip_readback_suffix(pv):
    for suffix in READBACK_SUFFIXES:
        if pv.endswith(suffix):
            return pv[:-len(suffix)]
    return pv
