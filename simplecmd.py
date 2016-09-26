#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import os.path
import signal
import sys

if (sys.version_info.major, sys.version_info.minor) < (3, 3):
    import subprocess32 as subprocess
else:
    import subprocess


class CommandError(Exception):
    """An error or timeout occured during the execution of a command."""
    pass


def cmd(command, shell=True, stderr=subprocess.STDOUT, timeout=300, **kwargs):
    """Execute a command using subprocess.check_output

    The executed command and the standard output are displayed when debug log
    level is enabled.

    By default, a timeout of 5 minutes is applied to all commands. To disable
    it, use timeout=None.

    Args: same as subprocess.check_output.

    Raise: subprocess.CalledProcessError

    Return: the standard output
    """
    kwargs.update({'shell': shell, 'stderr': stderr})
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50 + ' pwd = ' + kwargs.get('cwd', os.getcwd()))
        logging.debug('# BASH : %s', command)
        try:
            return _do_cmd(command, timeout, **kwargs)
        except CommandError as err:
            logging.error('%s', err)
            raise
    else:
        with open(os.devnull, 'wb') as devnull:
            kwargs['stderr'] = devnull
            return _do_cmd(command, timeout, **kwargs)


def _do_cmd(command, timeout, **kwargs):
    """Wrapper around subprocess to correctly kill children process groups in
    case of timeout.

    """
    # http://stackoverflow.com/questions/36952245/subprocess-timeout-failure
    kwargs['stdout'] = subprocess.PIPE
    kwargs['preexec_fn'] = os.setsid
    with subprocess.Popen(command, **kwargs) as proc:
        try:
            output, _ = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                raise CommandError('Command %s returned with code %d: %s' %
                                   command, proc.returncode, output)
            return output
        except subprocess.TimeoutExpired as err:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            raise CommandError("Command %s timed out." % command)
        except Exception as err:
            raise CommandError(str(err))
