"""Unit tests for the always up-to-date status comment of pull requests."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from bert_e import exceptions
from bert_e.workflow import pr_utils
from bert_e.workflow.gitwaterflow import (
    handle_comments, handle_pull_request, status_comment
)
from bert_e.workflow.gitwaterflow.status_comment import (
    State, ensure_status_comment, publish_status, render_status
)

ROBOT = 'robot'
STATUS = pr_utils.STATUS_COMMENT_HEADER + '\n\nsome status'


class FakeComment:
    def __init__(self, author, text):
        self.author = author
        self.text = text

    def edit(self, msg):
        self.text = msg


class FakePullRequest:
    id = 12

    def __init__(self, comments=()):
        self.comments = list(comments)
        self.added = 0

    def add_comment(self, msg):
        self.added += 1
        comment = FakeComment(ROBOT, msg)
        self.comments.append(comment)
        return comment


def make_job(pull_request=None, **settings):
    settings = dict(dict(robot=ROBOT, no_comment=False, interactive=False,
                         pr_status_comment=True, build_key='pre-merge'),
                    **settings)
    return SimpleNamespace(
        settings=SimpleNamespace(**settings),
        pull_request=pull_request or FakePullRequest(),
        active_options=['bypass_jira_check'],
        git=SimpleNamespace(src_branch=None, dst_branch=None, cascade=None),
    )


def instance(exc_class):
    """Instance of an exception, without rendering its template: only the
    class level description of the state matters here."""
    return exc_class.__new__(exc_class)


# --- which messages are states -------------------------------------------

@pytest.mark.parametrize('exc_class, label, status', [
    (exceptions.Conflict, 'Conflict', 'failure'),
    (exceptions.BuildFailed, 'Build failed', 'failure'),
    (exceptions.ApprovalRequired, 'Approval required', 'queued'),
    (exceptions.AfterPullRequest, 'Waiting for another pull request',
     'queued'),
    (exceptions.Queued, 'Queued', 'in_progress'),
    (exceptions.SuccessMessage, 'Merged', 'success'),
    (exceptions.PartialMerge, 'Partially merged', 'success'),
    (exceptions.QueueBuildFailedMessage, 'Queue build failed', 'failure'),
    (exceptions.ResetComplete, 'Reset complete', None),
    (exceptions.WrongDestination, 'Wrong destination', None),
    (exceptions.BuildInProgress, 'Waiting for the builds to complete',
     'in_progress'),
    (exceptions.BuildNotStarted, 'Waiting for the builds to start', None),
    (exceptions.PullRequestDeclined, 'Declined', None),
])
def test_states(exc_class, label, status):
    state = State.from_exception(instance(exc_class))
    assert (state.label, state.status) == (label, status)


@pytest.mark.parametrize('exc_class', [
    exceptions.InitMessage, exceptions.HelpMessage, exceptions.StatusReport,
    exceptions.CommandNotImplemented, exceptions.LossyResetWarning,
    exceptions.IntegrationDataCreated,
    exceptions.PendingHotfixVersionReminder,
    exceptions.NothingToDo, exceptions.NotMyJob,
    exceptions.CommentAlreadyExists, exceptions.JobSuccess,
])
def test_information_is_not_a_state(exc_class):
    assert State.from_exception(instance(exc_class)) is None


def test_every_information_exception_is_not_a_state():
    for exc_class in exceptions.InformationException.__subclasses__():
        assert State.from_exception(instance(exc_class)) is None


def test_final_states():
    final = [exceptions.SuccessMessage, exceptions.PartialMerge,
             exceptions.PullRequestDeclined]
    assert all(State.from_exception(instance(e)).final for e in final)
    assert not State.from_exception(instance(exceptions.Queued)).final
    assert not State.from_exception(instance(exceptions.Conflict)).final


# --- status comment recognition ------------------------------------------

def test_find_comment_ignores_the_status_comment():
    message = FakeComment(ROBOT, 'Hello')
    pull_request = FakePullRequest([
        message, FakeComment(ROBOT, STATUS),
        FakeComment('someone', 'thanks')])
    # Last message of the robot, and not its status comment
    assert pr_utils.find_comment(pull_request, ROBOT) is message
    assert pr_utils.find_comment(
        pull_request, ROBOT, 'Hello', max_history=-1) is message
    assert pr_utils.find_comment(
        FakePullRequest([FakeComment(ROBOT, STATUS)]), ROBOT) is None


def test_status_comment_must_be_authored_by_the_robot():
    pull_request = FakePullRequest([FakeComment('someone', STATUS)])
    assert pr_utils.find_status_comment(pull_request, ROBOT) is None
    assert not pr_utils.is_status_comment(pull_request.comments[0], ROBOT)


# --- publishing -----------------------------------------------------------

def test_publish_creates_then_edits_in_place():
    job = make_job()
    publish_status(job, instance(exceptions.BuildNotStarted), with_git=False)
    comment, = job.pull_request.comments
    assert comment.text.startswith(pr_utils.STATUS_COMMENT_HEADER)
    assert 'Waiting for the builds to start' in comment.text

    # same state: nothing to do
    publish_status(job, instance(exceptions.BuildNotStarted), with_git=False)
    assert job.pull_request.comments == [comment]

    publish_status(job, instance(exceptions.Conflict), with_git=False)
    assert job.pull_request.comments == [comment]
    assert 'Conflict' in comment.text
    assert 'Waiting' not in comment.text
    assert job.pull_request.added == 1


def test_publish_keeps_the_state_on_information():
    job = make_job()
    publish_status(job, instance(exceptions.Conflict), with_git=False)
    before = job.pull_request.comments[0].text
    publish_status(job, instance(exceptions.HelpMessage), with_git=False)
    assert job.pull_request.comments[0].text == before


@pytest.mark.parametrize('settings', [
    {'pr_status_comment': False}, {'no_comment': True},
    {'interactive': True},
])
def test_publish_can_be_disabled(settings):
    job = make_job(**settings)
    publish_status(job, instance(exceptions.Conflict), with_git=False)
    assert job.pull_request.comments == []


def test_publish_never_fails_on_expected_errors():
    job = make_job()
    job.pull_request.add_comment = MagicMock(
        side_effect=requests.HTTPError('boom'))
    publish_status(job, instance(exceptions.Conflict), with_git=False)

    job.pull_request.add_comment = MagicMock(
        side_effect=exceptions.FlakyGitHost(
            git_host='github', active_options=[]))
    publish_status(job, instance(exceptions.Conflict), with_git=False)


def test_publish_never_raises_on_unexpected_errors():
    job = make_job()
    job.pull_request.add_comment = MagicMock(side_effect=ValueError('bug'))
    publish_status(job, instance(exceptions.Conflict), with_git=False)


def test_publish_ignores_command_answers():
    job = make_job()
    publish_status(job, instance(exceptions.UnknownCommand), with_git=False)
    assert job.pull_request.comments == []


def test_publish_does_not_comment_old_declined_pull_requests():
    job = make_job()
    publish_status(job, instance(exceptions.PullRequestDeclined),
                   with_git=False)
    assert job.pull_request.comments == []


def test_ensure_creates_a_placeholder_only_once():
    job = make_job()
    ensure_status_comment(job)
    comment, = job.pull_request.comments
    assert 'Being analyzed' in comment.text
    assert 'integration branch' not in comment.text

    publish_status(job, instance(exceptions.Conflict), with_git=False)
    ensure_status_comment(job)
    assert job.pull_request.comments == [comment]
    assert 'Conflict' in comment.text


# --- integration pull requests ---------------------------------------------

def make_branch(name, sha):
    return SimpleNamespace(name=name, get_latest_commit=lambda: sha)


def make_pr(src_branch, pr_id, status='OPEN'):
    return SimpleNamespace(src_branch=src_branch, id=pr_id, status=status)


def make_git_job(branches, prs, builds):
    job = make_job()
    job.git.src_branch = job.git.dst_branch = object()
    job.project_repo = MagicMock()
    job.project_repo.get_pull_requests.return_value = prs
    job.project_repo.get_build_status.side_effect = \
        lambda sha, key: builds[sha]
    patcher = patch.object(status_comment, 'get_integration_branches',
                           return_value=iter(branches))
    return job, patcher


def test_integration_rows_follow_the_host():
    branches = [make_branch('w/5/feature/x', 'a'),
                make_branch('w/6/feature/x', 'b'),
                make_branch('w/7/feature/x', 'c')]
    # No pull request for w/7 (never created, or declined by a reset)
    prs = [make_pr('w/5/feature/x', 10), make_pr('w/6/feature/x', 11),
           make_pr('w/7/feature/x', 12, status='DECLINED')]
    builds = {'a': 'SUCCESSFUL', 'b': 'FAILED', 'c': 'INPROGRESS'}
    job, patcher = make_git_job(branches, prs, builds)
    with patcher:
        rows = status_comment._integration_rows(job)

    assert rows == [
        {'branch': 'w/5/feature/x', 'pr_id': 10, 'build': 'SUCCESSFUL'},
        {'branch': 'w/6/feature/x', 'pr_id': 11, 'build': 'FAILED'},
        {'branch': 'w/7/feature/x', 'pr_id': None, 'build': 'INPROGRESS'},
    ]
    job.project_repo.get_pull_requests.assert_called_once_with(
        src_branch=['w/5/feature/x', 'w/6/feature/x', 'w/7/feature/x'])


def test_integration_rows_without_build_key_nor_branches():
    job, patcher = make_git_job([make_branch('w/5/feature/x', 'a')], [], {})
    job.settings.build_key = ''
    with patcher:
        rows = status_comment._integration_rows(job)
    assert rows == [{'branch': 'w/5/feature/x', 'pr_id': None,
                     'build': None}]
    job.project_repo.get_build_status.assert_not_called()

    job, patcher = make_git_job([], [], {})
    with patcher:
        assert status_comment._integration_rows(job) == []
    job.project_repo.get_pull_requests.assert_not_called()


def test_render_status_with_git_data():
    job, patcher = make_git_job(
        [make_branch('w/5/feature/x', 'a')], [make_pr('w/5/feature/x', 10)],
        {'a': 'INPROGRESS'})
    report = {'approvals': SimpleNamespace(display_name='Approvals',
                                           details=['1 peer approval(s) '
                                                    'missing'], **{'pass': 0})}
    with patcher, patch.object(status_comment, 'clone_git_repo'), \
            patch.object(status_comment, '_build_status_report',
                         return_value=report):
        msg = render_status(job, State.from_exception(
            instance(exceptions.ApprovalRequired)))

    assert '`w/5/feature/x` | #10 | INPROGRESS' in msg
    assert '1 peer approval(s) missing' in msg


def test_final_state_has_no_integration_data():
    job, patcher = make_git_job(
        [make_branch('w/5/feature/x', 'a')], [], {'a': 'SUCCESSFUL'})
    with patcher as get_branches, \
            patch.object(status_comment, 'clone_git_repo') as clone, \
            patch.object(status_comment, '_build_status_report') as report:
        msg = render_status(job, State.from_exception(
            instance(exceptions.SuccessMessage)))

    assert 'Merged' in msg
    assert 'integration branch' not in msg
    assert 'check    | status' not in msg
    get_branches.assert_not_called()
    clone.assert_not_called()
    report.assert_not_called()


# --- integration in the workflow -------------------------------------------

def test_status_is_published_before_the_message():
    job = make_job()
    job.pull_request.author = 'someone'
    job.pull_request.src_branch = 'feature/x'
    error = exceptions.ResetComplete(couldnt_decline=[], active_options=[])
    calls = MagicMock()
    with patch('bert_e.workflow.gitwaterflow._handle_pull_request',
               side_effect=error), \
            patch('bert_e.workflow.gitwaterflow.publish_status',
                  calls.publish), \
            patch('bert_e.workflow.gitwaterflow.notify_user', calls.notify):
        with pytest.raises(exceptions.ResetComplete):
            handle_pull_request(job)

    assert [c[0] for c in calls.mock_calls] == ['publish', 'notify']
    calls.publish.assert_called_once_with(job, error)


@pytest.mark.parametrize('exc_class', [
    exceptions.BuildInProgress, exceptions.BuildNotStarted,
    exceptions.PullRequestDeclined])
def test_silent_states_are_published(exc_class):
    job = make_job()
    job.pull_request.author = 'someone'
    job.pull_request.src_branch = 'feature/x'
    with patch('bert_e.workflow.gitwaterflow._handle_pull_request',
               side_effect=exc_class()), \
            patch('bert_e.workflow.gitwaterflow.publish_status') as publish, \
            patch('bert_e.workflow.gitwaterflow.notify_user') as notify:
        with pytest.raises(exc_class):
            handle_pull_request(job)
    publish.assert_called_once()
    notify.assert_not_called()


def test_nothing_to_do_is_not_published():
    job = make_job()
    job.pull_request.author = 'someone'
    job.pull_request.src_branch = 'feature/x'
    with patch('bert_e.workflow.gitwaterflow._handle_pull_request',
               side_effect=exceptions.NothingToDo()), \
            patch('bert_e.workflow.gitwaterflow.publish_status') as publish:
        with pytest.raises(exceptions.NothingToDo):
            handle_pull_request(job)
    publish.assert_not_called()


def test_commands_are_looked_for_past_the_status_comment():
    """The status comment is not a message: a command posted before it, but
    after the last message, must still be handled, and the scan must stop at
    the last message."""
    pull_request = FakePullRequest([
        FakeComment('someone', '@robot old_command'),
        FakeComment(ROBOT, 'a message'),
        FakeComment('someone', '@robot status'),
        FakeComment(ROBOT, STATUS),
    ])
    pull_request.author = 'someone'
    job = make_job(pull_request, admins=[])
    with patch('bert_e.workflow.gitwaterflow.Reactor') as reactor_class:
        handle_comments(job)

    reactor = reactor_class.return_value
    reactor.handle_commands.assert_called_once_with(
        job, '@robot status', '@robot', False)
