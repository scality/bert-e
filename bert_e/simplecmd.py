#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2016 Scality
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import signal
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
        except CommandError:
            logging.exception("An exception occured while calling '%s'",
                              command)
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
    kwargs['universal_newlines'] = True
    with subprocess.Popen(command, **kwargs) as proc:
        try:
            output, _ = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                raise CommandError('Command %s returned with code %d: %s' %
                                   (command, proc.returncode, output))
            return output
        except subprocess.TimeoutExpired as err:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            raise CommandError("Command %s timed out." % command)
        except Exception as err:
            raise CommandError(str(err))
