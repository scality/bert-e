"""Webhooks of comments posted or edited by the robot must not create jobs."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bert_e.git_host import github
from bert_e.job import PullRequestJob
from bert_e.server import webhook
from bert_e.settings import UserSettingSchema


def make_bert_e(robot):
    # settings.robot is a UserDict in production, loaded from 'name[@id]'
    settings = SimpleNamespace(robot=UserSettingSchema().load(robot))
    return SimpleNamespace(settings=settings, client=None,
                           project_repo=SimpleNamespace(),
                           git_repo=SimpleNamespace())


def github_comment_event(action, sender_login):
    return {
        'action': action,
        'issue': {
            'number': 12,
            'title': 'A pull request',
            'pull_request': {
                'url': 'https://api.github.com/repos/o/r/pulls/12'},
        },
        'comment': {'id': 1, 'body': 'some text'},
        'sender': {'id': 3, 'login': sender_login, 'type': 'User'},
        'repository': {'full_name': 'o/r'},
    }


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
def test_github_robot_comment_is_ignored(action):
    bert_e = make_bert_e('robot_username')
    with patch.object(github.IssueCommentEvent, 'pull_request') as pr:
        job = webhook.handle_github_issue_comment(
            bert_e, github_comment_event(action, 'robot_username'))
    assert job is None
    # The pull request is not even fetched: no API call
    assert not pr.mock_calls


def test_github_robot_comment_login_case_insensitive():
    # Comment.author is lowercased: the filter compares the same way
    bert_e = make_bert_e('robot_username')
    job = webhook.handle_github_issue_comment(
        bert_e, github_comment_event('edited', 'Robot_Username'))
    assert job is None


@pytest.mark.parametrize('action', ['created', 'edited'])
def test_github_human_comment_creates_job(action):
    bert_e = make_bert_e('robot_username')
    pull_request = object()
    with patch.object(github.IssueCommentEvent, 'pull_request',
                      pull_request):
        job = webhook.handle_github_issue_comment(
            bert_e, github_comment_event(action, 'john_doe'))
    assert isinstance(job, PullRequestJob)
    assert job.pull_request is pull_request


def test_github_human_edits_robot_comment_creates_job():
    """The comment author is the robot, but a human performed the edit."""
    bert_e = make_bert_e('robot_username')
    data = github_comment_event('edited', 'john_doe')
    data['comment']['user'] = {'id': 3, 'login': 'robot_username'}
    with patch.object(github.IssueCommentEvent, 'pull_request', object()):
        job = webhook.handle_github_issue_comment(bert_e, data)
    assert isinstance(job, PullRequestJob)


def bitbucket_pr_event(actor):
    return {
        'actor': actor,
        'pullrequest': {'id': 1},
        'comment': {'id': 5, 'content': {'raw': 'some text'}},
    }


ROBOT_ACTOR = {'account_id': 'robot-account-id',
               'display_name': 'Bert-E', 'type': 'user'}
HUMAN_ACTOR = {'account_id': 'human-account-id',
               'display_name': 'John Doe', 'type': 'user'}


@pytest.fixture
def bb_bert_e():
    # On Bitbucket, BertE.__init__ sets robot.account_id from the API
    bert_e = make_bert_e('robot_username')
    bert_e.settings.robot.account_id = 'robot-account-id'
    return bert_e


@pytest.fixture
def mock_bb_pull_request():
    with patch.object(webhook, 'PullRequest') as pull_request:
        yield pull_request


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated',
                                   'comment_deleted'])
def test_bitbucket_robot_comment_is_ignored(bb_bert_e, mock_bb_pull_request,
                                            event):
    job = webhook.handle_bitbucket_pr_event(
        bb_bert_e, event, bitbucket_pr_event(ROBOT_ACTOR))
    assert job is None


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated'])
def test_bitbucket_human_comment_creates_job(bb_bert_e, mock_bb_pull_request,
                                             event):
    job = webhook.handle_bitbucket_pr_event(
        bb_bert_e, event, bitbucket_pr_event(HUMAN_ACTOR))
    assert isinstance(job, PullRequestJob)


@pytest.mark.parametrize('event', ['updated', 'created', 'approved'])
def test_bitbucket_robot_non_comment_event_creates_job(
        bb_bert_e, mock_bb_pull_request, event):
    """Only comment events are filtered: e.g. the robot opening an
    integration pull request still produces a job."""
    job = webhook.handle_bitbucket_pr_event(
        bb_bert_e, event, bitbucket_pr_event(ROBOT_ACTOR))
    assert isinstance(job, PullRequestJob)
