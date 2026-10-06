"""Unit tests of the filtering of the robot's own comment webhooks."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bert_e.git_host import github, mock
from bert_e.job import PullRequestJob
from bert_e.server import webhook
from bert_e.settings import UserDict
from bert_e.tests.test_server_data import COMMENT_CREATED


@pytest.fixture
def bert_e():
    settings = SimpleNamespace(
        robot=UserDict({'username': 'robot',
                        'account_id': 'robot-account-id'}))
    return SimpleNamespace(
        client=mock.Client('robot', 'password', 'robot@example.com'),
        settings=settings,
        project_repo=SimpleNamespace(owner='test_owner', slug='test_repo'),
        git_repo=SimpleNamespace())


def bitbucket_comment_payload(**actor):
    return dict(COMMENT_CREATED, actor=actor)


@pytest.mark.parametrize('event', webhook.BITBUCKET_COMMENT_EVENTS)
def test_bitbucket_robot_comment_ignored(bert_e, event):
    data = bitbucket_comment_payload(account_id='robot-account-id',
                                     username='other-name')
    assert webhook.handle_bitbucket_pr_event(bert_e, event, data) is None


def test_bitbucket_robot_comment_ignored_by_username(bert_e):
    data = bitbucket_comment_payload(username='Robot')
    assert webhook.handle_bitbucket_pr_event(
        bert_e, 'comment_created', data) is None


@pytest.mark.parametrize('event', webhook.BITBUCKET_COMMENT_EVENTS)
def test_bitbucket_human_comment_handled(bert_e, event):
    data = bitbucket_comment_payload(account_id='human-account-id',
                                     username='john_doe')
    job = webhook.handle_bitbucket_pr_event(bert_e, event, data)
    assert isinstance(job, PullRequestJob)
    assert job.pull_request.id == 1


def test_bitbucket_robot_pr_update_handled(bert_e):
    """Only the robot's comments are filtered, not its other events."""
    data = bitbucket_comment_payload(account_id='robot-account-id')
    job = webhook.handle_bitbucket_pr_event(bert_e, 'updated', data)
    assert isinstance(job, PullRequestJob)


def github_issue_comment_payload(action, sender):
    return {
        'action': action,
        'issue': {
            'number': 3,
            'title': 'title',
            'pull_request': {
                'url': 'https://api.github.com/repos/o/r/pulls/3'},
        },
        'comment': {'id': 1, 'body': 'text',
                    'user': {'id': 2, 'login': sender}},
        'sender': {'id': 2, 'login': sender},
        'repository': {'full_name': 'o/r'},
    }


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
def test_github_robot_comment_ignored(bert_e, action):
    data = github_issue_comment_payload(action, 'Robot')
    with patch.object(github.PullRequest, 'get') as get_pr:
        assert webhook.handle_github_issue_comment(bert_e, data) is None
    # no API call is spent on the robot's own comments
    get_pr.assert_not_called()


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
def test_github_human_comment_handled(bert_e, action):
    data = github_issue_comment_payload(action, 'john_doe')
    pr = object()
    with patch.object(github.PullRequest, 'get', return_value=pr) as get_pr:
        job = webhook.handle_github_issue_comment(bert_e, data)
    get_pr.assert_called_once()
    assert isinstance(job, PullRequestJob)
    assert job.pull_request is pr


def test_github_comment_without_sender_handled(bert_e):
    data = github_issue_comment_payload('created', 'john_doe')
    del data['sender']
    pr = object()
    with patch.object(github.PullRequest, 'get', return_value=pr):
        job = webhook.handle_github_issue_comment(bert_e, data)
    assert job.pull_request is pr
