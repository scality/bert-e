"""Unit tests for the rows of the /status report."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bert_e import exceptions as exns
from bert_e.workflow.gitwaterflow import commands


def _job(**settings):
    defaults = dict(build_key='pre-merge', wait=False, use_queue=False,
                    bypass_build_status=False)
    defaults.update(settings)
    return SimpleNamespace(settings=SimpleNamespace(**defaults),
                           project_repo=Mock(), active_options=[],
                           author_bypass={})


def _branch(name, sha):
    return SimpleNamespace(name=name, get_latest_commit=lambda: sha)


def test_builds_lists_every_failing_branch_with_link():
    job = _job()
    states = {'a': 'SUCCESSFUL', 'b': 'FAILED', 'c': 'INPROGRESS'}
    job.project_repo.get_build_status.side_effect = lambda sha, key: states[
        sha]
    job.project_repo.get_build_url.side_effect = (
        lambda sha, key: 'https://ci/{}'.format(sha) if sha == 'b' else None)
    branches = [_branch('w/1', 'a'), _branch('w/2', 'b'),
                _branch('w/3', 'c')]
    with patch.object(commands, 'get_integration_branches',
                      return_value=branches):
        item = commands._check_builds_status(job)
    assert getattr(item, 'pass') is False
    assert not item.pending
    assert item.details == ['w/2: FAILED ([build](https://ci/b))',
                            'w/3: INPROGRESS']


def test_builds_pending_without_integration_branches():
    job = _job()
    with patch.object(commands, 'get_integration_branches',
                      return_value=[]):
        item = commands._check_builds_status(job)
    assert item.pending
    assert 'not yet evaluated' in item.details[0]


def test_wait_row():
    assert commands._check_wait_status(_job()) is None
    item = commands._check_wait_status(_job(wait=True))
    assert getattr(item, 'pass') is False


def test_queue_row_disabled():
    assert commands._check_queue_status(_job()) is None


def test_queue_row_states():
    job = _job(use_queue=True)
    branches = [_branch('w/1', 'a')]
    with patch.object(commands, 'get_integration_branches',
                      return_value=branches), \
            patch('bert_e.workflow.gitwaterflow.queueing.already_in_queue',
                  return_value=True):
        item = commands._check_queue_status(job)
    assert getattr(item, 'pass') and item.details == ['queued']
    with patch.object(commands, 'get_integration_branches',
                      return_value=branches), \
            patch('bert_e.workflow.gitwaterflow.queueing.already_in_queue',
                  return_value=False):
        item = commands._check_queue_status(job)
    assert item.pending


def test_template_renders_every_state():
    report = {
        'ok': commands._StatusItem('Satisfied', True),
        'bypassed': commands._StatusItem('Bypassed', True, ['bypassed']),
        'ko': commands._StatusItem('Missing', False, ['author approval']),
        'wait': commands._StatusItem('Pending', False, ['not yet'],
                                     pending=True),
    }
    msg = exns.StatusReport(status=report, active_options=[]).msg
    assert '**Satisfied** | :sunny:\n' in msg
    assert '**Bypassed** | :sunny: bypassed' in msg
    assert '**Missing** | :exclamation: author approval' in msg
    assert '**Pending** | :hourglass: not yet' in msg
