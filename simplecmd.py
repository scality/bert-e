#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import os.path
import sys

if (sys.version_info.major, sys.version_info.minor) < (3, 3):
    import subprocess32 as subprocess
else:
    import subprocess


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
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50 + ' pwd = ' + kwargs.get('cwd', os.getcwd()))
        logging.debug('# BASH : %s', command)
        return subprocess.check_output(command, shell=shell, stderr=stderr,
                                       timeout=timeout, **kwargs)
    else:
        with open(os.devnull, 'wb') as devnull:
            return subprocess.check_output(
                command, shell=shell, stderr=devnull, timeout=timeout, **kwargs
            )
