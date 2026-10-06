"""Unit tests of the filtering of comment webhooks sent by the robot."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from requests import HTTPError

from bert_e.git_host import github
from bert_e.job import PullRequestJob
from bert_e.server import webhook

ROBOT_ACCOUNT_ID = '557058:0b2c6f1e-robot'


@pytest.fixture
def bert_e(settings):
    # settings.robot is a UserDict built from settings.sample.yml
    return SimpleNamespace(
        settings=settings, client=object(),
        project_repo=SimpleNamespace(owner='test_owner', slug='test_repo'),
        git_repo=SimpleNamespace())


@pytest.fixture
def bitbucket_bert_e(bert_e):
    # Set by BertE.__init__ on Bitbucket, from the robot's credentials
    bert_e.settings.robot.account_id = ROBOT_ACCOUNT_ID
    return bert_e


def bitbucket_comment_event(account_id, nickname):
    return {
        'actor': {
            'account_id': account_id,
            'display_name': nickname.title(),
            'nickname': nickname,
            'type': 'user',
            'uuid': '{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}',
        },
        'comment': {
            'id': 21710334,
            'content': {'raw': 'some text'},
            'user': {'account_id': account_id},
        },
        'pullrequest': {
            'id': 4,
            'destination': {
                'repository': {'full_name': 'test_owner/test_repo'},
            },
        },
    }


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated',
                                   'comment_deleted'])
def test_bitbucket_robot_comment_ignored(bitbucket_bert_e, event):
    data = bitbucket_comment_event(ROBOT_ACCOUNT_ID, 'robot_username')
    assert webhook.handle_bitbucket_pr_event(
        bitbucket_bert_e, event, data) is None


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated'])
def test_bitbucket_human_comment_handled(bitbucket_bert_e, event):
    data = bitbucket_comment_event('557058:john-doe', 'john_doe')
    job = webhook.handle_bitbucket_pr_event(bitbucket_bert_e, event, data)
    assert isinstance(job, PullRequestJob)
    assert job.pull_request.id == 4


def test_bitbucket_robot_pull_request_event_handled(bitbucket_bert_e):
    """Only comment events of the robot are filtered."""
    data = bitbucket_comment_event(ROBOT_ACCOUNT_ID, 'robot_username')
    del data['comment']
    job = webhook.handle_bitbucket_pr_event(bitbucket_bert_e, 'updated', data)
    assert isinstance(job, PullRequestJob)


GITHUB_ISSUE_COMMENT = {
    'action': 'created',
    'issue': {
        'number': 4,
        'title': 'Some PR',
        'pull_request': {
            'url': 'https://api.github.com/repos/octo-org/hello/pulls/4',
        },
    },
    'comment': {
        'id': 42,
        'body': 'some text',
        'user': {'id': 1, 'login': 'robot_username'},
    },
    'sender': {'id': 1, 'login': 'robot_username', 'type': 'User'},
}


def github_issue_comment(action, login):
    data = deepcopy(GITHUB_ISSUE_COMMENT)
    data['action'] = action
    data['comment']['user']['login'] = login
    data['sender']['login'] = login
    return data


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
@pytest.mark.parametrize('login', ['robot_username', 'Robot_Username'])
def test_github_robot_comment_ignored(bert_e, action, login):
    with patch.object(github.PullRequest, 'get') as get_pr:
        job = webhook.handle_github_issue_comment(
            bert_e, github_issue_comment(action, login))
    assert job is None
    # The pull request is not even fetched: no API call is spent
    get_pr.assert_not_called()


@pytest.mark.parametrize('action', ['created', 'edited'])
def test_github_human_comment_handled(bert_e, action):
    pull_request = object()
    with patch.object(github.PullRequest, 'get',
                      return_value=pull_request) as get_pr:
        job = webhook.handle_github_issue_comment(
            bert_e, github_issue_comment(action, 'john_doe'))
    assert isinstance(job, PullRequestJob)
    assert job.pull_request is pull_request
    get_pr.assert_called_once()


def test_github_human_comment_on_missing_pr(bert_e):
    with patch.object(github.PullRequest, 'get', side_effect=HTTPError()):
        assert webhook.handle_github_issue_comment(
            bert_e, github_issue_comment('created', 'john_doe')) is None


@pytest.mark.parametrize('user_id,expected', [
    ('robot_username', True),
    ('ROBOT_USERNAME', True),
    (ROBOT_ACCOUNT_ID, True),
    ('john_doe', False),
    ('', False),
    (None, False),
])
def test_is_robot(bitbucket_bert_e, user_id, expected):
    assert webhook.is_robot(bitbucket_bert_e, user_id) is expected


def test_is_robot_without_account_id(bert_e):
    """On GitHub, the robot has no account_id."""
    assert bert_e.settings.robot.account_id is None
    assert webhook.is_robot(bert_e, 'robot_username')
    assert not webhook.is_robot(bert_e, 'None')
