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
from types import SimpleNamespace

import pytest

from bert_e.reactor import (Command, InvalidSyntax, NotAuthored, NotFound,
                            NotPrivileged, Option, Reactor)


# All tests are run on a Reactor subclass to avoid sharing state.

@pytest.fixture
def reactor_cls():
    class ReactorTest(Reactor):
        pass

    return ReactorTest


@pytest.fixture
def job():
    return SimpleNamespace(settings={})


def test_add_option(reactor_cls):
    """Test options are correctly registered using Reactor.add_option."""

    reactor_cls.add_option('my_option')
    reactor_cls.add_option('other_option', "help for other_option",
                           default=False)
    reactor_cls.add_option('privileged_option', "help for privileged_option",
                           default=False, privileged=True)

    options = reactor_cls.get_options()
    assert 'my_option' in options
    assert 'other_option' in options
    assert 'privileged_option' in options

    assert len(options) == 4

    my_option = options['my_option']
    other_option = options['other_option']
    privileged_option = options['privileged_option']

    assert isinstance(my_option, Option)
    assert my_option.help is None
    assert not my_option.privileged

    assert isinstance(other_option, Option)
    assert other_option.help == "help for other_option"
    assert not other_option.privileged

    assert isinstance(privileged_option, Option)
    assert privileged_option.help == "help for privileged_option"
    assert privileged_option.privileged


def test_option_decorator(reactor_cls):
    """Test options are correctly registered using Reactor.option decorator."""

    @reactor_cls.option
    def my_option(job, *args):
        """Help for my_option"""
        pass

    @reactor_cls.option(help_="Help for another_option")
    def another_option(job, *args):
        pass

    @reactor_cls.option(default=False)
    def some_option(job, *args):
        pass

    @reactor_cls.option(privileged=True)
    def privileged_option(job, *args):
        pass

    @reactor_cls.option(key='custom_key')
    def custom_key_option(job, *args):
        pass

    options = reactor_cls.get_options()

    assert 'my_option' in options
    assert 'another_option' in options
    assert 'some_option' in options
    assert 'privileged_option' in options
    assert 'custom_key' in options

    assert len(options) == 6

    assert options['my_option'].handler == my_option
    assert options['my_option'].help == my_option.__doc__
    assert options['my_option'].default is None
    assert not options['my_option'].privileged

    assert options['another_option'].handler == another_option
    assert options['another_option'].help == "Help for another_option"

    assert options['some_option'].handler == some_option
    assert options['some_option'].default is False

    assert options['privileged_option'].handler == privileged_option
    assert options['privileged_option'].privileged

    assert options['custom_key'].handler == custom_key_option
    assert options['custom_key'].help is None


def test_options_behavior(reactor_cls, job):
    """Test behavior of simple options."""

    reactor_cls.add_option('my_option')
    reactor_cls.add_option('default_option', default=True)
    reactor_cls.add_option('privileged_option', privileged=True)

    reactor = reactor_cls()

    reactor.init_settings(job)

    assert job.settings == {
        'after_pull_request': set(),
        'my_option': None,
        'default_option': True,
        'privileged_option': None,
    }

    reactor.handle_options(job, '!set my_option', '!set')
    assert job.settings['my_option'] is True

    with pytest.raises(NotFound):
        reactor.handle_options(job, '!set blablabla', '!set')

    with pytest.raises(NotPrivileged):
        reactor.handle_options(job, '!set privileged_option', '!set')
    assert not job.settings['privileged_option']

    reactor.handle_options(job, '!set privileged_option', '!set', True)
    assert job.settings['privileged_option'] is True

    job.settings['my_option'] = None

    reactor.handle_options(job, '!set my_option', '!other_prefix')
    assert job.settings['my_option'] is None


def test_add_command(reactor_cls):
    """Test commands are correctly registered using Reactor.add_command."""

    def my_command(job, *args):
        pass

    def other_command(job, *args):
        """

        Help for other_command.

        TBA

        """
        pass

    def privileged_command(job, *args):
        pass

    reactor_cls.add_command('my_command', my_command)
    reactor_cls.add_command('my_command2', my_command, 'help for my_command2')
    reactor_cls.add_command('other_command', other_command)
    reactor_cls.add_command('privileged_command', privileged_command,
                            privileged=True)

    commands = reactor_cls.get_commands()

    assert 'my_command' in commands
    assert 'my_command2' in commands
    assert 'other_command' in commands
    assert 'privileged_command' in commands

    assert isinstance(commands['my_command'], Command)
    assert commands['my_command'].handler == my_command
    assert commands['my_command'].help is None
    assert not commands['my_command'].privileged

    assert commands['my_command2'].handler == my_command
    assert commands['my_command2'].help == 'help for my_command2'

    assert commands['other_command'].handler == other_command
    assert commands['other_command'].help == 'Help for other_command. TBA'

    assert commands['privileged_command'].handler == privileged_command
    assert commands['privileged_command'].privileged


def test_command_decorator(reactor_cls):
    """Test commands are correctly registered using Reactor.command."""

    @reactor_cls.command
    @reactor_cls.command('my_command2', help_='help for my_command2')
    def my_command(job, *args):
        pass

    @reactor_cls.command
    def other_command(job, *args):
        """Help for other_command"""
        pass

    @reactor_cls.command(privileged=True)
    def privileged_command(job, *args):
        pass

    commands = reactor_cls.get_commands()

    assert 'my_command' in commands
    assert 'my_command2' in commands
    assert 'other_command' in commands
    assert 'privileged_command' in commands

    assert isinstance(commands['my_command'], Command)
    assert commands['my_command'].handler == my_command
    assert commands['my_command'].help is None
    assert not commands['my_command'].privileged

    assert commands['my_command2'].handler == my_command
    assert commands['my_command2'].help == 'help for my_command2'

    assert commands['other_command'].handler == other_command
    assert commands['other_command'].help == 'Help for other_command'

    assert commands['privileged_command'].handler == privileged_command
    assert commands['privileged_command'].privileged


def test_command_behavior(reactor_cls, job):
    """Test behavior of commands."""

    class CommandCalled(Exception):
        def __init__(self, job, args):
            self.job = job
            self.args = args

    @reactor_cls.command('privileged_cmd', privileged=True)
    @reactor_cls.command
    def cmd(job, *args):
        raise CommandCalled(job, args)

    reactor = reactor_cls()

    with pytest.raises(CommandCalled) as call:
        reactor.handle_commands(job, '!do cmd', '!do')

    assert call.value.job is job
    assert call.value.args == ()

    with pytest.raises(CommandCalled) as call:
        reactor.handle_commands(job, '!do cmd with args', '!do')

    assert call.value.args == ('with', 'args')

    with pytest.raises(NotFound):
        reactor.handle_commands(job, '!do command', '!do')

    try:
        reactor.handle_commands(job, '!do cmd', '!other_prefix')
    except CommandCalled:
        assert False, "Command shouldn't have been called"

    with pytest.raises(NotPrivileged):
        reactor.handle_commands(job, '!do privileged_cmd', '!do')

    with pytest.raises(CommandCalled) as call:
        reactor.handle_commands(job, '!do privileged_cmd arg', '!do',
                                privileged=True)

    assert call.value.args == ('arg',)


def test_handle_commands_slash_shorthand(reactor_cls, job):
    """Test the ``/keyword`` shorthand supported by handle_commands."""

    class CommandCalled(Exception):
        def __init__(self, args):
            self.args = args

    @reactor_cls.command
    def help(job, *args):
        raise CommandCalled(args)

    reactor = reactor_cls()

    with pytest.raises(CommandCalled):
        reactor.handle_commands(job, '/help', '@bert-e')


def test_handle_commands_slash_shorthand_unknown_dropped(reactor_cls, job):
    """Unknown ``/keyword`` comments that aren't close to any registered
    command or option are dropped silently so foreign-bot mentions don't
    produce noisy "unknown command" replies."""

    @reactor_cls.command
    def help(job, *args):
        pass

    reactor = reactor_cls()

    # Comments addressed to other bots don't resemble any bert-e command
    # and are silently ignored.
    reactor.handle_commands(job, '/coderabbit review', '@bert-e')
    reactor.handle_commands(job, '/gemini review this PR', '@bert-e')
    reactor.handle_commands(job, '/copilot summary', '@bert-e')

    # Same on the options path: the strict options regex matches a bare
    # ``/coderabbit`` and previously raised NotFound. With the fuzzy-match
    # guard, unknown foreign keywords are dropped silently.
    reactor.handle_options(job, '/coderabbit', '@bert-e')


def test_handle_commands_slash_shorthand_typo_raises(reactor_cls, job):
    """``/keyword`` typos of a registered command still raise NotFound so
    the caller can post a "did you mean?" reply."""

    @reactor_cls.command
    def help(job, *args):
        pass

    reactor = reactor_cls()

    # ``hlep`` is a close difflib match to ``help`` -> still surfaces as
    # an unknown command.
    with pytest.raises(NotFound):
        reactor.handle_commands(job, '/hlep', '@bert-e')


def test_handle_options_slash_shorthand_typo_raises(reactor_cls, job):
    """Typos of a registered option on the ``/`` path still raise NotFound."""

    reactor_cls.add_option('approve', authored=True)

    reactor = reactor_cls()
    reactor.init_settings(job)

    with pytest.raises(NotFound):
        reactor.handle_options(job, '/apporve', '@bert-e', authored=True)


def test_at_prefix_unknown_still_raises(reactor_cls, job):
    """Comments that explicitly address the bot with ``@<robot>`` never
    silently drop unknown commands, even when the keyword isn't close to
    any registered one."""

    @reactor_cls.command
    def help(job, *args):
        pass

    reactor = reactor_cls()

    # ``@bert-e coderabbit`` is not close to any bert-e command, but because
    # the user is explicitly addressing the bot, we still raise NotFound.
    with pytest.raises(NotFound):
        reactor.handle_commands(job, '@bert-e coderabbit', '@bert-e')


def test_reactor_has_close_match(reactor_cls, job):
    """Directly exercise the fuzzy-match helper on a controlled registry."""

    reactor_cls.add_option('approve', authored=True)

    @reactor_cls.command
    def help(job, *args):
        pass

    reactor = reactor_cls()

    # Typos of registered keywords are recognised (case-insensitive).
    assert reactor._has_close_match('apporve') is True
    assert reactor._has_close_match('APPORVE') is True
    assert reactor._has_close_match('hlep') is True

    # Foreign-bot names bear no resemblance to registered keywords.
    assert reactor._has_close_match('coderabbit') is False
    assert reactor._has_close_match('gemini') is False
    assert reactor._has_close_match('copilot') is False
    assert reactor._has_close_match('other-bot-name') is False


@pytest.fixture
def option_reactor(reactor_cls):
    """Reactor holding a few options and commands mimicking GitWaterFlow's."""

    @reactor_cls.option(key='after_pull_request', default=set(),
                        usage='after_pull_request=<pr_id>')
    def after_pull_request(job, pr_id=None):
        if pr_id is None:
            raise InvalidSyntax('after_pull_request')
        job.settings['after_pull_request'].add(pr_id)

    reactor_cls.add_option('wait')
    reactor_cls.add_option('approve', authored=True)
    reactor_cls.add_option('bypass_build_status', privileged=True)

    @reactor_cls.command
    def status(job, *args):
        job.settings['status'] = args

    @reactor_cls.command
    def help(job, *args):
        job.settings['help'] = args

    return reactor_cls


@pytest.mark.parametrize('text,keyword', [
    ('/after_pull_request 1509', 'after_pull_request'),
    ('/after_pull_request=1509 please', 'after_pull_request'),
    ('/wait please', 'wait'),
    ('/approve LGTM', 'approve'),
    ('/approve\nLGTM, nice work', 'approve'),
    ('@bert-e after_pull_request #1509', 'after_pull_request'),
    ('@bert-e: wait!', 'wait'),
])
def test_handle_options_malformed_option_raises(option_reactor, job, text,
                                                keyword):
    """An exact option keyword followed by a malformed rest raises
    InvalidSyntax naming the option."""
    reactor = option_reactor()
    reactor.init_settings(job)

    with pytest.raises(InvalidSyntax) as excinfo:
        reactor.handle_options(job, text, '@bert-e', authored=True)

    assert excinfo.value.keyword == keyword
    assert job.settings['after_pull_request'] == set()


@pytest.mark.parametrize('text', [
    '/coderabbit review',
    '/gemini review this PR',
    '/status please',
    '/status',
    '/help',
    '@bert-e status please',
    'free text mentioning /after_pull_request 1509',
    '/After_pull_request 1509',
    '/after_pull_requests 1509',
    '/wait-for-ci',
    '/wait-for-ci please',
    '/wait.ci please',
])
def test_handle_options_malformed_ignored(option_reactor, job, text):
    """Comments whose first keyword is not exactly an option are left to the
    existing logic and do not raise InvalidSyntax."""
    reactor = option_reactor()
    reactor.init_settings(job)

    reactor.handle_options(job, text, '@bert-e', authored=True)

    assert job.settings['after_pull_request'] == set()
    assert job.settings['wait'] is None


@pytest.mark.parametrize('text', [
    '/approve /wait',
    '@bert-e approve wait',
])
def test_handle_options_multi_options(option_reactor, job, text):
    reactor = option_reactor()
    reactor.init_settings(job)

    reactor.handle_options(job, text, '@bert-e', authored=True)

    assert job.settings['approve'] is True
    assert job.settings['wait'] is True


@pytest.mark.parametrize('text', [
    '/after_pull_request=1509 /wait',
    '@bert-e after_pull_request=1509 wait',
])
def test_handle_options_multi_options_with_value(option_reactor, job, text):
    reactor = option_reactor()
    reactor.init_settings(job)

    reactor.handle_options(job, text, '@bert-e')

    assert job.settings['after_pull_request'] == {'1509'}
    assert job.settings['wait'] is True


def test_handle_options_handler_raises_invalid_syntax(option_reactor, job):
    """A handler can raise InvalidSyntax itself (missing argument)."""
    reactor = option_reactor()
    reactor.init_settings(job)

    with pytest.raises(InvalidSyntax):
        reactor.handle_options(job, '/after_pull_request', '@bert-e')


def test_handle_commands_ignore_malformed_option(option_reactor, job):
    """handle_commands keeps ignoring option keywords silently, so the
    syntax error is only reported once, by handle_options."""
    reactor = option_reactor()
    reactor.init_settings(job)

    reactor.handle_commands(job, '/after_pull_request 1509', '@bert-e')
    reactor.handle_commands(job, '/wait please', '@bert-e')
    reactor.handle_commands(job, '/status please', '@bert-e')
    assert job.settings['status'] == ('please',)
    with pytest.raises(NotFound):
        reactor.handle_commands(job, '/hlep', '@bert-e')


def test_get_usage(option_reactor):
    assert option_reactor.get_usage('after_pull_request') == \
        'after_pull_request=<pr_id>'
    assert option_reactor.get_usage('wait') == 'wait'
    assert option_reactor.get_usage('status') is None
    assert option_reactor.get_usage('unknown') is None


@pytest.mark.parametrize('text,keyword', [
    ('/approve /after_pull_request 12', 'after_pull_request'),
    ('@bert-e approve after_pull_request #12', 'after_pull_request'),
    ('/wait /approve please', 'approve'),
    ('/approve /wait\nLGTM', 'wait'),
    ('/approve /wait-for-ci', 'approve'),
])
def test_handle_options_malformed_later_option(option_reactor, job, text,
                                               keyword):
    """The malformed option is blamed, not the first (valid) keyword."""
    reactor = option_reactor()
    reactor.init_settings(job)

    with pytest.raises(InvalidSyntax) as excinfo:
        reactor.handle_options(job, text, '@bert-e', authored=True)

    assert excinfo.value.keyword == keyword


@pytest.mark.parametrize('text,exc', [
    ('/approve LGTM', NotAuthored),
    ('@bert-e approve LGTM', NotAuthored),
    ('/bypass_build_status please', NotPrivileged),
    ('/wait /bypass_build_status please', NotPrivileged),
    ('/bypass_build_status /approve please', NotPrivileged),
])
def test_handle_options_malformed_unauthorized(option_reactor, job, text,
                                               exc):
    """A malformed option posted by a user who may not use it reports the
    missing rights, as a well-formed declaration would, instead of an
    incorrect syntax message suggesting the forbidden option."""
    reactor = option_reactor()
    reactor.init_settings(job)

    with pytest.raises(exc):
        reactor.handle_options(job, text, '@bert-e')


def test_handle_options_malformed_authorized(option_reactor, job):
    reactor = option_reactor()
    reactor.init_settings(job)

    with pytest.raises(InvalidSyntax) as excinfo:
        reactor.handle_options(job, '/bypass_build_status please', '@bert-e',
                               privileged=True)
    assert excinfo.value.keyword == 'bypass_build_status'


@pytest.mark.parametrize('text', [
    '/approve-deploy',
    '/bypass_build_status-check please',
])
def test_handle_options_compound_word_unauthorized_ignored(option_reactor,
                                                           job, text):
    """A ``/`` word that only starts with an option name (e.g.
    ``/approve-deploy``) is not an option: no rights error is raised."""
    reactor = option_reactor()
    reactor.init_settings(job)

    reactor.handle_options(job, text, '@bert-e')

    assert job.settings['approve'] is None
