# Copyright 2016-2018 Scality
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

"""
This module implements an independent command reactor.

The reactor is intended to hold the definition and implementation of commands
that the user might want BertE to react to while parsing a pull request's
comments.

We distinguish two classes of "commands":

    * Command: Perform an immediate action of any kind.
    * Option: Set an option for the whole lifetime of a pull request.

Commands have the following attributes:

    * handler: a function that takes a job as its first argument (and an
      arbitrarily long list of arguments).

    * help: a string intended to be displayed when the user requests the
      command's manual.

    * privileged: a boolean indicating if the command is to be performed
      by privileged users only.

Options have an additional `default` attribute that describes the option's
default value.

The Reactor class implemented in this module is intended to be plugin-friendly.
If one wants to add new options or commands to the reactor, all he has to do
is register them using the corresponding class methods.

Examples:

    >>> from bert_e.reactor import Reactor
    >>> from types import SimpleNamespace

    Register an unprivileged command to the 'say_hi' key, using the
    function's docstring as the command's help:

    >>> @Reactor.command
    ... def say_hi(job, *args):
    ...     '''Print 'hi' in the console.'''
    ...     print("hi")

    Register a privileged command to the 'shutdown' key:

    >>> @Reactor.command(privileged=True)
    ... def shutdown(job, *args):
    ...     '''Shut the application down.'''
    ...     print("Shutting down the application")
    ...     raise SystemExit(0)

    Register a privileged command using custom help string:

    >>> @Reactor.command(privileged=True, help_='Execute a shell command.')
    ... def shell(job, *args):
    ...     '''Run a command in the shell.'''
    ...     print("Executing a privileged command.")

    Register a boolean option that will be set in job.settings to `True`
    when called by a privileged user. Default value is `None`:

    >>> Reactor.add_option('bypass_checks', privileged=True)

    Register an unprivileged option with special behavior:

    >>> @Reactor.option(key='after_pull_request', default=set())
    ... def after_pr(job, pr_id):
    ...     job.settings['after_pull_request'].add(pr_id)
    ...

    To use the Reactor, instanciate it:

    >>> reactor = Reactor()
    >>> job = SimpleNamespace(settings={})
    >>> reactor.handle_commands(job, '!do say_hi', prefix='!do')
    hi
    >>>
    >>> reactor.handle_commands(job, '!do shell ls', prefix='!do')
    Traceback (most recent call last):
        [...]
    bert_e.reactor.NotPrivileged
    >>> reactor.handle_commands(job, '!do shell ls', prefix='!do',
    ...                         privileged=True)
    Executing a privileged command.

    Initializing a job's settings to the registered default values:

    >>> reactor.init_settings(job)
    >>> job.settings
    {'after_pull_request': set(), 'bypass_checks': None}

    Executing option-related commands:

    >>> reactor.handle_options(job, '!do after_pull_request=4', '!do')
    >>> reactor.handle_options(job, '!do bypass_checks', '!do',
    ...                        privileged=True)
    >>> job.settings
    {'after_pull_request': {'4'}, 'bypass_checks': True}

    Note that you can pass mutable objets as default values, they are copied
    during initialization of the settings:

    >>> reactor.init_settings(job)
    >>> job.settings
    {'after_pull_request': set(), 'bypass_checks': None}

"""

# Please note that special effort was made to keep this module relatively
# independent from the rest of the application.
# Its only non-standard dependencies are the Dispatcher utility mixin,
# and the fact that a 'job' must have a 'settings' dictionary-like attribute.

import logging
import re
from collections import namedtuple
from copy import copy

from .lib.dispatcher import Dispatcher


class Error(Exception):
    """Base class for errors raised in this module."""
    pass


class NotPrivileged(Error):
    """A non-privileged user tried to use a privileged command or option."""
    def __init__(self, keyword: str):
        super().__init__()
        self.keyword = keyword


class NotAuthored(Error):
    """A user tried to use an author only command or option."""
    def __init__(self, keyword: str):
        super().__init__()
        self.keyword = keyword


class NotFound(Error):
    """The requested command or option doesn't exist."""
    def __init__(self, keyword: str):
        super().__init__()
        self.keyword = keyword


LOG = logging.getLogger(__name__)

Command = namedtuple('Command', ['handler', 'help', 'privileged', 'authored'])
Option = namedtuple('Option', ['handler', 'default', 'help', 'privileged',
                               'authored'])


def normalize_whitespace(msg):
    """Sanitize help message by removing extra white space.

    This helps keeping clean help messages when passed through a function's
    docstring.

    """
    if msg is None:
        return msg
    return ' '.join(msg.strip().split())


class Reactor(Dispatcher):
    """Central dispatching class for comment-based commands and options."""

    @classmethod
    def add_command(cls, key, handler, help_=None, privileged=False,
                    authored=False):
        """Register a new command to the reactor."""
        help_ = normalize_whitespace(help_ or handler.__doc__)
        cls.set_callback(key, Command(handler, help_, privileged, authored))

    @classmethod
    def command(cls, key=None, help_=None, privileged=False):
        """Decorator to register a command.

        Args:
            key: the key to register the command to. Defaults to the
                 decorated function's name.
            help_: the help message of the command. Defaults to the
                   decorated function's docstring.
            privileged: whether the command is privileged or not. Defaults to
                        False.
        """

        if callable(key):
            # the decorator was called with the @Reactor.command syntax
            func = key
            cls.add_command(func.__name__, func, func.__doc__, False)
            return func

        # the decorator was called with the @Reactor.command(...) syntax
        def decorator(func):
            _key = key or func.__name__
            _help = help_ or func.__doc__
            cls.add_command(_key, func, _help, privileged)
            return func

        return decorator

    @classmethod
    def add_option(cls, key, help_=None, privileged=False, default=None,
                   authored=False):
        """Add a basic option to the reactor."""

        def set_option(job, arg=True):
            job.settings[key] = arg

        help_ = normalize_whitespace(help_)
        cls.set_callback(key, Option(set_option, default, help_, privileged,
                                     authored))

    @classmethod
    def option(cls, key=None, default=None, help_=None, privileged=False,
               authored=False):
        """Decorator to register an option handler.

        Args:
            default: the setting's default value. Defaults to None.

        See Reactor.commands() for detail on other args.

        """

        if callable(key):
            # The decorator was called with the @Reactor.option syntax
            func = key
            help_ = normalize_whitespace(help_ or func.__doc__)
            cls.set_callback(
                func.__name__, Option(func, default, help_, privileged,
                                      authored)
            )
            return func

        # the decorator was called with the @Reactor.option(...) syntax
        def decorator(func):
            _key = key or func.__name__
            _help = normalize_whitespace(help_ or func.__doc__)
            cls.set_callback(_key, Option(func, default, _help, privileged,
                                          authored))
            return func
        return decorator

    @classmethod
    def get_options(cls):
        """Return a dictionary depicting currently registered options."""
        return {key: val for key, val in cls.__callbacks__.items()
                if isinstance(val, Option)}

    @classmethod
    def get_commands(cls):
        """Return a dictionary depicting currently registered commands."""
        return {key: val for key, val in cls.__callbacks__.items()
                if isinstance(val, Command)}

    def init_settings(self, job):
        """Initialize a job's settings to the registered options' default
        values.

        """
        for key, option in self.get_options().items():
            job.settings[key] = copy(option.default)

    def handle_options(self, job, text, prefix, privileged=False,
                       authored=False):
        """Find option calls in given text string, and execute the
        corresponding option handlers if any is found.

        An option declaration can be on the following forms:

            {prefix}option1=val1 option2
            {prefix}: option1=val1, option2
            {prefix}: option1=val1 - option2

        The text is ignored if:
            * the option declaration is actually a command call,
            * there is no option declaration in it.

        Args:
            job: the job to run the handlers on.
            text: the text to look for option calls in.
            prefix: the prefix of commands.
            privileged: run the option handler in privileged mode. Defaults to
                        False.

        Raises:
            NotFound: if the option declaration has the right syntax but calls
                      an unknown option.
            NotPrivileged: when a privileged option declaration is found
                           and the method is called with privileged=False.
            NotAuthored: when an authored option declaration is found and the
                         method is called with authored=False.

        """
        raw = text.strip()
        real_prefix = None
        if raw.startswith(prefix):
            real_prefix = prefix
        elif raw.startswith('/'):
            real_prefix = '/'
        if not real_prefix:
            return
        LOG.debug('Found a potential option: %r', raw)
        cleaned = re.sub(r'[,.\-/:;|+]', ' ', raw[len(real_prefix):])
        match = re.match(r'%s(?P<keywords>(\s*[\w=]+)+)\s*$' % real_prefix,
                         cleaned)
        if not match:
            LOG.debug('Ignoring comment. Unknown format')
            return

        keywords = match.group('keywords').strip().split()

        LOG.debug('checking keywords %s', keywords)

        for idx, kwd in enumerate(keywords):
            key, *args = kwd.split('=')
            option = self.dispatch(key)
            if option is None:
                raise NotFound(key)
            if not isinstance(option, Option):
                if idx == 0:
                    # It's a command, ignore it
                    return
                else:
                    raise NotFound(key)

            if option.privileged and not privileged:
                raise NotPrivileged(key)

            if option.authored and not authored:
                raise NotAuthored(key)

            # Everything is okay, apply the option
            option.handler(job, *args)

    def handle_commands(self, job, text, prefix, privileged=False):
        """Find a command call in given text string, and execute the
        corresponding handler if any is found.

        An command call can be on the following forms:

            {prefix} command arg1 arg2 ...

        The text is ignored if:
            * the command call is actually an opotion declaration,
            * there is no command call in it.

        Args:
            job: the job to run the handlers on.
            text: the text to look for command calls in.
            prefix: the prefix of commands.
            privileged: run the command handler in privileged mode. Defaults to
                        False.

        Raises:
            NotFound: if the command call has the right syntax but calls
                      an unknown command.
            NotPrivileged: when a privileged command call is found
                           and the method is called with privileged=False.

        """
        raw = text.strip()
        regex_prefix = None
        if raw.startswith(prefix):
            regex_prefix = '%s[\s:]*' % prefix
        elif raw.startswith('/'):
            regex_prefix = '/'
        if not regex_prefix:
            return
        LOG.debug('Found a potential command: %r', raw)
        regex = r"%s(?P<command>[A-Za-z_]+[^= ,])(?P<args>.*)$" % regex_prefix
        match = re.match(regex, raw)
        if not match:
            LOG.warning("Command ignored. Unknown format.")
            return

        key, args = match.group('command'), match.group('args').split()
        command = self.dispatch(key)
        if command is None:
            raise NotFound(key)
        if not isinstance(command, Command):
            return

        if command.privileged and not privileged:
            raise NotPrivileged(key)

        # Execute the command
        command.handler(job, *args)
