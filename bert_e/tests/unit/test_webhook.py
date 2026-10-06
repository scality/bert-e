"""Filtering of the comment webhooks triggered by the robot itself."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests_mock

from bert_e.git_host import github
from bert_e.job import PullRequestJob
from bert_e.server import webhook
from bert_e.tests.test_server_data import COMMENT_CREATED

GH_BASE = 'https://api.github.com'
GH_PR_URL = GH_BASE + '/repos/octo/repo/pulls/5'
ROBOT_ACCOUNT_ID = '557058:robot-account'


def github_issue_comment(action, sender_login):
    return {
        'action': action,
        'issue': {'number': 5, 'title': 'title',
                  'pull_request': {'url': GH_PR_URL}},
        'comment': {'id': 1, 'body': 'hello',
                    'user': {'id': 1, 'login': sender_login}},
        'sender': {'id': 1, 'login': sender_login},
        'repository': {'full_name': 'octo/repo'},
    }


@pytest.fixture
def github_bert_e(settings):
    client = github.Client(login='robot_username', password='password',
                           email='email@org.com', base_url=GH_BASE)
    return SimpleNamespace(settings=settings, client=client,
                           project_repo=SimpleNamespace(),
                           git_repo=SimpleNamespace())


@pytest.fixture
def bitbucket_bert_e(settings):
    # BertE.__init__ fills the robot's account id on Bitbucket.
    settings.robot.account_id = ROBOT_ACCOUNT_ID
    return SimpleNamespace(settings=settings, client=None,
                           project_repo=SimpleNamespace(),
                           git_repo=SimpleNamespace())


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
@pytest.mark.parametrize('login', ['robot_username', 'Robot_Username'])
def test_github_robot_comment_ignored(github_bert_e, action, login):
    with requests_mock.Mocker() as m:
        job = webhook.handle_github_issue_comment(
            github_bert_e, github_issue_comment(action, login))
    assert job is None
    # The pull request is not even fetched.
    assert m.call_count == 0


@pytest.mark.parametrize('action', ['created', 'edited'])
def test_github_human_comment_handled(github_bert_e, action):
    pr_data = {'number': 5, 'url': GH_PR_URL, 'title': 'title',
               'user': {'id': 2, 'login': 'human'}}
    with requests_mock.Mocker() as m:
        m.get(GH_PR_URL, json=pr_data)
        job = webhook.handle_github_issue_comment(
            github_bert_e, github_issue_comment(action, 'human'))
    assert isinstance(job, PullRequestJob)
    assert job.pull_request.id == 5


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated',
                                   'comment_deleted'])
def test_bitbucket_robot_comment_ignored(bitbucket_bert_e, event):
    data = deepcopy(COMMENT_CREATED)
    data['actor'] = {'account_id': ROBOT_ACCOUNT_ID,
                     'nickname': 'robot_username', 'display_name': 'Robot'}
    assert webhook.handle_bitbucket_pr_event(
        bitbucket_bert_e, event, data) is None


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated'])
def test_bitbucket_human_comment_handled(bitbucket_bert_e, event):
    data = deepcopy(COMMENT_CREATED)
    data['actor'] = {'account_id': '557058:human-account',
                     'nickname': 'robot_username', 'display_name': 'Human'}
    job = webhook.handle_bitbucket_pr_event(bitbucket_bert_e, event, data)
    assert isinstance(job, PullRequestJob)
    assert job.pull_request.id == 1


def test_bitbucket_robot_pr_update_handled(bitbucket_bert_e):
    """Only comment events are filtered, not other pull request events."""
    data = deepcopy(COMMENT_CREATED)
    data['actor'] = {'account_id': ROBOT_ACCOUNT_ID}
    job = webhook.handle_bitbucket_pr_event(bitbucket_bert_e, 'updated', data)
    assert isinstance(job, PullRequestJob)
