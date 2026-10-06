# Copyright 2016-2026 Scality
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
"""Webhook filtering of comment events sent by the robot itself."""

import base64
import json
from copy import deepcopy
from queue import Queue
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bert_e import server
from bert_e.git_host import github
from bert_e.git_host import mock as mock_api
from bert_e.lib.settings_dict import SettingsDict
from bert_e.settings import UserSettingSchema

from .test_server_data import COMMENT_CREATED

ROBOT_ACCOUNT_ID = '557058:robot-account-id'

GH_PULL_REQUEST_URL = 'https://api.github.com/repos/owner/slug/pulls/1'


def make_bert_e(host):
    robot = UserSettingSchema().load('robot_user')
    if host == 'bitbucket':
        # BertE.__init__ fetches the robot's account_id on Bitbucket
        robot.account_id = ROBOT_ACCOUNT_ID
    task_queue = Queue()
    return SimpleNamespace(
        client=mock_api.Client('login', 'password', 'email'),
        git_repo=SimpleNamespace(),
        settings=SettingsDict({'repository_host': host, 'robot': robot,
                               'pr_author_options': {}}),
        project_repo=SimpleNamespace(owner='test_owner', slug='test_repo',
                                     full_name='test_owner/test_repo'),
        task_queue=task_queue,
        put_job=task_queue.put,
    )


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setenv('WEBHOOK_LOGIN', 'dummy')
    monkeypatch.setenv('WEBHOOK_PWD', 'dummy')
    monkeypatch.setenv('BERT_E_CLIENT_ID', 'dummy_client_id')
    monkeypatch.setenv('BERT_E_CLIENT_SECRET', 'dummy_client_secret')

    def _client(host):
        bert_e = make_bert_e(host)
        app = server.setup_server(bert_e)
        auth = base64.b64encode(b'dummy:dummy').decode()

        def post(headers, data):
            headers = dict(headers, Authorization='Basic ' + auth)
            return app.test_client().post(
                '/' + host, data=json.dumps(data), headers=headers)
        return bert_e, post
    return _client


def bitbucket_comment_event(**actor):
    data = deepcopy(COMMENT_CREATED)
    data['repository']['owner']['username'] = 'test_owner'
    data['repository']['name'] = 'test_repo'
    data['actor'].update(actor)
    return data


def github_comment_event(sender_login, action='created'):
    user = {'id': 1, 'login': sender_login}
    return {
        'action': action,
        'issue': {'number': 1, 'pull_request': {'url': GH_PULL_REQUEST_URL}},
        'comment': {'id': 42, 'body': 'some text', 'user': user},
        'repository': {'full_name': 'test_owner/test_repo'},
        'sender': user,
    }


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated',
                                   'comment_deleted'])
def test_bitbucket_robot_comment_ignored(webhook_client, event):
    # Bitbucket Cloud identifies the actor by account_id (no username since
    # its 2019 privacy changes), matched against robot.account_id.
    bert_e, post = webhook_client('bitbucket')
    resp = post({'X-Event-Key': 'pullrequest:' + event},
                bitbucket_comment_event(account_id=ROBOT_ACCOUNT_ID,
                                        nickname='robot_user'))
    assert resp.status_code == 200
    assert bert_e.task_queue.empty()


@pytest.mark.parametrize('event', ['comment_created', 'comment_updated'])
def test_bitbucket_human_comment_handled(webhook_client, event):
    bert_e, post = webhook_client('bitbucket')
    resp = post({'X-Event-Key': 'pullrequest:' + event},
                bitbucket_comment_event(account_id='557058:john-doe',
                                        nickname='john_doe'))
    assert resp.status_code == 200
    job = bert_e.task_queue.get_nowait()
    assert job.pull_request.id == 1


def test_bitbucket_robot_non_comment_event_handled(webhook_client):
    """Only comment events are filtered: the robot's other PR events
    (e.g. it updated or approved a pull request) still trigger a job."""
    bert_e, post = webhook_client('bitbucket')
    resp = post({'X-Event-Key': 'pullrequest:updated'},
                bitbucket_comment_event(account_id=ROBOT_ACCOUNT_ID,
                                        nickname='robot_user'))
    assert resp.status_code == 200
    assert bert_e.task_queue.get_nowait().pull_request.id == 1


@pytest.mark.parametrize('action', ['created', 'edited', 'deleted'])
@pytest.mark.parametrize('login', ['robot_user', 'Robot_User'])
def test_github_robot_comment_ignored(webhook_client, action, login):
    bert_e, post = webhook_client('github')
    with patch.object(github.PullRequest, 'get') as get_pr:
        resp = post({'X-Github-Event': 'issue_comment'},
                    github_comment_event(login, action))
    assert resp.status_code == 200
    assert bert_e.task_queue.empty()
    # The robot's comments do not cost an API call to fetch the PR
    get_pr.assert_not_called()


@pytest.mark.parametrize('action', ['created', 'edited'])
def test_github_human_comment_handled(webhook_client, action):
    bert_e, post = webhook_client('github')
    pull_request = github.PullRequest(client=bert_e.client, _validate=False,
                                      number=1)
    with patch.object(github.PullRequest, 'get',
                      return_value=pull_request) as get_pr:
        resp = post({'X-Github-Event': 'issue_comment'},
                    github_comment_event('john_doe', action))
    assert resp.status_code == 202
    get_pr.assert_called_once_with(client=bert_e.client,
                                   url=GH_PULL_REQUEST_URL)
    assert bert_e.task_queue.get_nowait().pull_request is pull_request


def test_github_human_edits_robot_comment_handled(webhook_client):
    """The webhook sender, not the comment's author, is checked: a human
    editing one of the robot's comments still triggers a job."""
    bert_e, post = webhook_client('github')
    data = github_comment_event('john_doe', 'edited')
    data['comment']['user'] = {'id': 2, 'login': 'robot_user'}
    pull_request = github.PullRequest(client=bert_e.client, _validate=False,
                                      number=1)
    with patch.object(github.PullRequest, 'get', return_value=pull_request):
        resp = post({'X-Github-Event': 'issue_comment'}, data)
    assert resp.status_code == 202
    assert not bert_e.task_queue.empty()
