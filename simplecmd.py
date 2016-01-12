#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import logging
import os


def cmd(command, shell=True, stderr=None, **kwargs):
    """Execute a command using subprocess.check_output

    The executed command and the standard output are displayed when debug log
    level is enabled.

    Args: same as subprocess.check_output.

    Raise: subprocess.CalledProcessError

    Return: the standard output
    """
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50)
        logging.debug('# BASH : %s', command)

        return subprocess.check_output(command, shell=shell, stderr=stderr,
                                       **kwargs)
    else:
        with open(os.devnull, 'wb') as devnull:
            return subprocess.check_output(command, shell=shell,
                                           stderr=devnull, **kwargs)
