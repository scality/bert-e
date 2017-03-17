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
"""Wrapper around subprocess to launch commands in a shell-like fashion."""
import logging
import os
import signal
import subprocess

LOG = logging.getLogger(__name__)


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
    pwd = kwargs.get('mask_pwd', None)

    def mask_pwd(data):
        return data.replace(pwd, '***') if pwd else data

    kwargs.update({'shell': shell, 'stderr': stderr})
    if LOG.isEnabledFor(logging.DEBUG):
        LOG.debug('[%s] %s', kwargs.get('cwd', os.getcwd()), mask_pwd(command))
        return _do_cmd(command, timeout, **kwargs)

    else:
        with open(os.devnull, 'wb') as devnull:
            kwargs['stderr'] = devnull
            return _do_cmd(command, timeout, **kwargs)


def _do_cmd(command, timeout, **kwargs):
    """Wrapper around subprocess to correctly kill children process groups in
    case of timeout.

    """
    pwd = kwargs.pop('mask_pwd', None)

    def mask_pwd(data):
        return data.replace(pwd, '***') if pwd else data

    # http://stackoverflow.com/questions/36952245/subprocess-timeout-failure
    kwargs['stdout'] = subprocess.PIPE
    kwargs['preexec_fn'] = os.setsid
    kwargs['universal_newlines'] = True
    with subprocess.Popen(command, **kwargs) as proc:
        try:
            output, _ = proc.communicate(timeout=timeout)
            output = mask_pwd(output)
            if proc.returncode != 0:
                LOG.debug("[%s] {returned %d}",
                          kwargs.get('cwd', os.getcwd()), proc.returncode)
                raise CommandError(
                    'Command %s returned with code %d: %s' %
                    (mask_pwd(command), proc.returncode, output)
                )
            return output
        except subprocess.TimeoutExpired as err:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            LOG.debug("[%s] {timed out}", kwargs.get('cwd', os.getcwd()))
            raise CommandError(
                "Command %s timed out." % mask_pwd(command)) from err
        except CommandError:
            raise
        except Exception as err:
            raise CommandError(mask_pwd(str(err))) from err
