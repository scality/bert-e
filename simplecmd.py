#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import subprocess

import os
import os.path


def cmd(command, shell=True, stderr=subprocess.STDOUT, **kwargs):
    """Execute a command using subprocess.check_output

    The executed command and the standard output are displayed when debug log
    level is enabled.

    Args: same as subprocess.check_output.

    Raise: subprocess.CalledProcessError

    Return: the standard output
    """
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug('')
        logging.debug('#' * 50 + ' pwd = ' + kwargs.get('cwd', os.getcwd()))
        logging.debug('# BASH : %s', command)
        return subprocess.check_output(command, shell=shell, stderr=stderr,
                                       **kwargs)
    else:
        with open(os.devnull, 'wb') as devnull:
            return subprocess.check_output(command, shell=shell,
                                           stderr=devnull, **kwargs)
