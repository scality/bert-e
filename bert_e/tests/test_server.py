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

import base64
import json
import os
import pathlib
import re
import unittest
import unittest.mock
from collections import OrderedDict, deque
from copy import deepcopy
from datetime import datetime
from queue import Queue
from types import SimpleNamespace

from .. import job as berte_job
from .. import bert_e, server
from ..jobs.create_branch import CreateBranchJob
from ..jobs.delete_branch import DeleteBranchJob
from ..jobs.eval_pull_request import EvalPullRequestJob
from ..jobs.delete_queues import DeleteQueuesJob
from ..jobs.force_merge_queues import ForceMergeQueuesJob
from ..jobs.rebuild_queues import RebuildQueuesJob
from ..git_host import bitbucket as bitbucket_api
from ..git_host import cache
from ..git_host import mock as mock_api
from ..lib.settings_dict import SettingsDict
from .test_server_data import COMMENT_CREATED, COMMIT_STATUS_CREATED

bitbucket_api.PullRequest = mock_api.PullRequest
SETTINGS_FILE = (pathlib.Path(__file__).parent.parent.parent /
                 'settings.sample.yml')


class MockBertE(bert_e.BertE):
    def __init__(self, *args, **kwargs):
        self.client = mock_api.Client("login", "password", "email")
        self.project_repo = SimpleNamespace(
            owner='test_owner',
            slug='test_repo'
        )
        self.settings = SettingsDict
        self.git_repo = SimpleNamespace()
        self.task_queue = Queue()
        self.tasks_done = deque(maxlen=1000)
        self.status = {}

        self.settings.repository_host = 'bitbucket'
        self.settings.repository_owner = 'owner'
        self.settings.repository_slug = 'slug'
        self.settings.build_key = 'pre-merge'
        self.settings.pull_request_base_url = \
            'https://bitbucket.org/foo/bar/pull-requests/{pr_id}'
        self.settings.commit_base_url = \
            'https://bitbucket.org/foo/bar/commits/{commit_id}'
        self.settings.admins = ['test_admin', 'test_admin_2']


class TestServer(unittest.TestCase):
    def setUp(self):
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'
        os.environ['BERT_E_CLIENT_ID'] = 'dummy_client_id'
        os.environ['BERT_E_CLIENT_SECRET'] = 'dummy_client_secret'

        server.BERTE = MockBertE()
        server.APP = server.setup_server(server.BERTE)

    def test_client(self, user=None):
        """A Flask test client, with session configured.

        Args:
            - user (str): name of user, or None if not authenticated

        """
        client = server.APP.test_client()
        with client.session_transaction() as session:
            assert session.get('user') is None
            assert session.get('admin') is None
            session['user'] = user
            session['admin'] = user in server.BERTE.settings.admins

        return client

    def handle_webhook(self, event_type, data):

        server.BERTE.project_repo.owner = \
            data['repository']['owner']['username']
        server.BERTE.project_repo.slug = data['repository']['name']

        client = self.test_client()
        auth = ''.join(
            (os.environ['WEBHOOK_LOGIN'], ':', os.environ['WEBHOOK_PWD'])
        )
        basic_auth = 'Basic ' + base64.b64encode(auth.encode()).decode()
        return client.post(
            '/bitbucket', data=json.dumps(data),
            headers={'X-Event-Key': event_type, 'Authorization': basic_auth}
        )

    def handle_api_call(self, command, data={}, method='POST', user=None):
        with self.test_client(user=user) as c:
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            return getattr(c, method.lower())(
                '/api/%s' % command,
                data=json.dumps(data),
                headers=headers
            )

    def test_comment_added(self):
        resp = self.handle_webhook('pullrequest:comment_created',
                                   COMMENT_CREATED)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)

        job = server.BERTE.task_queue.get()
        self.assertEqual(job.project_repo.owner, 'test_owner')
        self.assertEqual(job.project_repo.slug, 'test_repo')
        # self.assertEqual(job.repo_settings, u'/bert-e/test_owner/test_repo')
        self.assertEqual(job.pull_request.id, 1)

        server.BERTE.task_queue.task_done()
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 0)

    def test_build_status_filtered(self):
        data = deepcopy(COMMIT_STATUS_CREATED)
        data['commit_status']['state'] = 'INPROGRESS'
        resp = self.handle_webhook('repo:commit_status_created', data)

        self.assertEqual(200, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 0)

        data['commit_status']['state'] = 'SUCCESSFUL'
        resp = self.handle_webhook('repo:commit_status_created', data)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)

        # consume job
        server.BERTE.task_queue.get()
        server.BERTE.task_queue.task_done()

    def test_bert_e_status(self):
        server.BERTE.status['merge queue'] = OrderedDict([
            ('10', [('4.3', '0033deadbeef'), ('6.0', '13370badf00d')])
        ])
        self.set_status_cache('0033deadbeef', 'INPROGRESS', 'fakeurl')

        server.BERTE.status['merged PRs'] = [
            {'id': 1, 'merge_time': datetime(2016, 12, 9, 14, 54, 20, 123456)},
            {'id': 2, 'merge_time': datetime(2016, 12, 9, 14, 54, 21, 123456)},
            {'id': 3, 'merge_time': datetime(2016, 12, 8, 14, 54, 22, 123456)}
        ]

        client = self.test_client()
        res = client.get('/?output=txt')
        data = res.data.decode()

        # Check merged Pull Requests and merge queue status appear in monitor
        # view
        assert 'Recently merged pull requests:' in data
        assert '* [2016-12-09 14:54:20] - #1\n' in data
        assert '* [2016-12-09 14:54:21] - #2\n' in data
        assert '* [2016-12-08 14:54:22] - #3\n' in data
        assert 'Merge queue status:' in data
        assert '   #10       NOTSTARTED     INPROGRESS  ' in data

        res = client.get('/')
        data = res.data.decode()
        assert 'Recently merged' in data
        assert '2016-12-09 14:54:20' in data
        assert '<a href="https://bitbucket.org/foo/bar/pull-requests/1" target="_blank">Pull request #1</a>' in data  # noqa
        assert '2016-12-09 14:54:21'
        assert '<a href="https://bitbucket.org/foo/bar/pull-requests/2" target="_blank">Pull request #2</a>' in data  # noqa
        assert '2016-12-08 14:54:22' in data
        assert '<a href="https://bitbucket.org/foo/bar/pull-requests/3" target="_blank">Pull request #3</a>' in data  # noqa
        assert 'Merge queue status' in data
        assert '<a href="https://bitbucket.org/foo/bar/pull-requests/10" target="_blank">' in data  # noqa
        assert '<span class="text-dark">PR #10</span>' in data
        assert '<span class="text-info"><img src="/static/inprogress.png" alt="INPROGRESS"></span>' in data  # noqa
        assert '<span class="text-secondary"><img src="/static/notstarted.png" alt="NOTSTARTED"></span>' in data  # noqa

        # Update cache with a successful and a failed build
        self.set_status_cache('0033deadbeef', 'FAILED', 'url2')
        self.set_status_cache('13370badf00d', 'SUCCESSFUL', 'url3')

        res = client.get('/?output=txt')
        data = res.data.decode()
        assert '   #10       SUCCESSFUL       FAILED    ' in data

        res = client.get('/')
        data = res.data.decode()
        assert '<span class="text-success"><img src="/static/successful.png" alt="SUCCESSFUL"></span>' in data  # noqa
        assert '<span class="text-danger"><img src="/static/failed.png" alt="FAILED"></span>' in data  # noqa

        # Everything is merged, the queue status shouldn't appear anymore
        server.BERTE.status['merged PRs'].append({
            'id': 10,
            'merge_time': datetime(2016, 12, 9, 14, 54, 20, 123456)
        })
        res = client.get('/?output=txt')
        data = res.data.decode()
        # PR #10 should appear as merged
        assert '* [2016-12-09 14:54:20] - #10' in data
        assert 'Merge queue status:' not in data

        res = client.get('/')
        data = res.data.decode()
        assert '2016-12-09 14:54:20' in data
        assert '<a href="https://bitbucket.org/foo/bar/pull-requests/10" target="_blank">Pull request #10</a>' in data  # noqa

    def set_status_cache(self, sha1, state, url,
                         description='dummy', key='pre-merge'):
        json_data = {
            'description': description,
            'key': key,
            'state': state,
            'url': url,
        }
        status = bitbucket_api.BuildStatus(None, **json_data)
        cache.BUILD_STATUS_CACHE[key].set(sha1, status)

    def test_merge_queue_print(self):
        server.BERTE.status['merge queue'] = OrderedDict([
            (4472, [
                ('6', '4472/6'),
                ('6.4', '4472/6.4'),
                ('6.3', '4472/6.3'),
                ('6.2', '4472/6.2')]),
            ('5773', [
                ('6', '5773/6'),
                ('6.4', '5773/6.4')]),
            ('6050', [
                ('6', '6050/6'),
                ('6.4', '6050/6.4')]),
            ('6086', [
                ('6', '6086/6'),
                ('6.4', '6086/6.4'),
                ('6.3.0', '6086/6.3.0'),
                ('6.3', '6086/6.3')]),
            ('5095', [
                ('6', '5095/6'),
                ('6.4', '5095/6.4')]),
        ])

        self.set_status_cache('4472/6', 'SUCCESSFUL', '4472/6_url')
        self.set_status_cache('4472/6.4', 'SUCCESSFUL', '4472/6.4_url')
        self.set_status_cache('4472/6.3', 'SUCCESSFUL', '4472/6.3_url')
        self.set_status_cache('4472/6.2', 'INPROGRESS', '4472/6.2_url')
        self.set_status_cache('5773/6', 'FAILED', '5773/6_url')
        self.set_status_cache('5773/6.4', 'FAILED', '5773/6.4_url')
        self.set_status_cache('6050/6', 'SUCCESSFUL', '6050/6_url')
        self.set_status_cache('6050/6.4', 'SUCCESSFUL', '6050/6.4_url')
        self.set_status_cache('6086/6', 'FAILED', '6086/6_url')
        self.set_status_cache('6086/6.4', 'FAILED', '6086/6.4_url')
        self.set_status_cache('6086/6.3.0', 'SUCCESSFUL', '6086/6.3.0_url')
        self.set_status_cache('6086/6.3', 'SUCCESSFUL', '6086/6.3_url')
        self.set_status_cache('5095/6', 'SUCCESSFUL', '5095/6_urltoto')
        self.set_status_cache('5095/6.4', 'SUCCESSFUL', '5095/6.4_urltoto')

        expected = (
            'Merge queue status:',
            '                 6             6.4            6.3           6.3.0           6.2      \n', # noqa
            '  #4472      SUCCESSFUL     SUCCESSFUL     SUCCESSFUL                    INPROGRESS  \n', # noqa
            '  #5773        FAILED         FAILED                                                 \n', # noqa
            '  #6050      SUCCESSFUL     SUCCESSFUL                                               \n', # noqa
            '  #6086        FAILED         FAILED       SUCCESSFUL     SUCCESSFUL                 \n', # noqa
            '  #5095      SUCCESSFUL     SUCCESSFUL'  # noqa
        )

        client = self.test_client()
        res = client.get('/?output=txt')
        data = res.data.decode()
        for exp in expected:
            self.assertIn(exp, data)

        expected = (
            '<h2>Merge queue status</h2>',
            '        <tr>\n'
            '          <th scope="row">\n'
            '            <a href="https://bitbucket.org/foo/bar/pull-requests/6086" target="_blank">\n'  # noqa
            '              <span class="text-dark">PR #6086</span>\n'
            '            </a>\n'
            '          </th>\n'
            '          <td class="text-center">\n'
            '            <a href="6086/6_url" target="_blank">\n'
            '              <span class="text-danger"><img src="/static/failed.png" alt="FAILED"></span>\n'  # noqa
            '            </a>\n'
            '          </td>\n'
            '          <td class="text-center">\n'
            '            <a href="6086/6.4_url" target="_blank">\n'
            '              <span class="text-danger"><img src="/static/failed.png" alt="FAILED"></span>\n'  # noqa
            '            </a>\n'
            '          </td>\n'
            '          <td class="text-center">\n'
            '            <a href="6086/6.3_url" target="_blank">\n'
            '              <span class="text-success"><img src="/static/successful.png" alt="SUCCESSFUL"></span>\n'  # noqa
            '            </a>\n'
            '          </td>\n'
            '          <td class="text-center">\n'
            '            <a href="6086/6.3.0_url" target="_blank">\n'
            '              <span class="text-success"><img src="/static/successful.png" alt="SUCCESSFUL"></span>\n'  # noqa
            '            </a>\n'
            '          </td>\n'
            '          <td class="text-center">\n'
            '            <span class="text-dark"></span>\n'
            '          </td>\n'
            '        </tr>'  # noqa
        )
        res = client.get('/')
        data = res.data.decode()
        for exp in expected:
            self.assertIn(exp, data)

    def test_current_job_print(self):
        job = berte_job.CommitJob(
            bert_e=server.BERTE,
            commit="456deadbeef12345678901234567890123456789"
        )
        job.start_time = datetime(2016, 12, 8, 14, 54, 20, 123456)
        server.BERTE.status['current job'] = job

        client = self.test_client()
        res = client.get('/?output=txt')
        data = res.data.decode()

        assert 'Current job: [2016-12-08 14:54:20]' \
               ' - Webhook for commit 456deadb' in data

    def test_pending_jobs_print(self):
        job = berte_job.CommitJob(
            bert_e=server.BERTE,
            commit="123deadbeef12345678901234567890123456789"
        )
        job.start_time = datetime(2016, 12, 8, 14, 54, 18, 123456)
        server.BERTE.put_job(job)

        job = berte_job.PullRequestJob(
            bert_e=server.BERTE,
            pull_request=SimpleNamespace(id=666)
        )
        job.start_time = datetime(2016, 12, 8, 14, 54, 19, 123456)
        job.status = 'NothingToDo'
        job.details = 'details'
        server.BERTE.put_job(job)

        expected = (
            '2 pending jobs:',
            '* [2016-12-08 14:54:18] - Webhook for commit 123deadb',
            '* [2016-12-08 14:54:19] - Webhook for pull request #666'
        )

        client = self.test_client()
        res = client.get('/?output=txt')
        data = res.data.decode()

        for exp in expected:
            self.assertIn(exp, data)

        expected = (
            '<h2>Jobs</h2>',
            '2016-12-08 14:54:18',
            '<a href="https://bitbucket.org/foo/bar/commits/123deadbeef12345678901234567890123456789" target="_blank">Webhook for commit 123deadb</a>',  # noqa
            '2016-12-08 14:54:19',
            '<a href="https://bitbucket.org/foo/bar/pull-requests/666" target="_blank">Webhook for pull request #666</a>',  # noqa
        )

        res = client.get('/')
        data = res.data.decode()
        for exp in expected:
            self.assertIn(exp, data)

    def test_completed_jobs_print(self):

        job = berte_job.CommitJob(
            bert_e=server.BERTE,
            commit="123deadbeef12345678901234567890123456789"
        )
        job.start_time = datetime(2016, 12, 8, 14, 54, 18, 123456)
        job.status = 'NothingToDo'
        server.BERTE.tasks_done.appendleft(job)

        job = berte_job.PullRequestJob(
            bert_e=server.BERTE,
            pull_request=SimpleNamespace(id=666)
        )
        job.start_time = datetime(2016, 12, 8, 14, 54, 19, 123456)
        job.status = 'NothingToDo'
        job.details = 'details'
        server.BERTE.tasks_done.appendleft(job)

        expected = (
            'Completed jobs:',
            '* [2016-12-08 14:54:19] - '
            'Webhook for pull request #666 -> NothingToDo\ndetails',
            '* [2016-12-08 14:54:18] - '
            'Webhook for commit 123deadb -> NothingToDo'
        )

        client = self.test_client()
        res = client.get('/?output=txt')
        data = res.data.decode()
        for exp in expected:
            self.assertIn(exp, data)

        expected = (
            '<h3>Completed jobs:</h3>',
            '<li>[2016-12-08 14:54:19] - '
            '<a href="https://bitbucket.org/foo/bar/pull-requests/666"'
            ' target="_blank">Webhook for pull request #666</a>'
            ' -> NothingToDo'
            '<p>details</p></li>',
            '<li>[2016-12-08 14:54:18] - '
            '<a href="https://bitbucket.org/foo/bar/commits/123deadbeef12345678901234567890123456789"'  # noqa
            ' target="_blank">'
            'Webhook for commit 123deadb</a> '
            '-> NothingToDo</li>'
        )

        expected = (
            '  <h2>Jobs</h2>\n'
            '  <div class="bert-e-job pb-2">\n'
            '    <div class="row text-dark">\n'
            '      <div class="col-3">\n'
            '        2016-12-08 14:54:19\n'
            '      </div>\n'
            '      <div class="col-5">\n'
            '        <a href="https://bitbucket.org/foo/bar/pull-requests/666" target="_blank">Webhook for pull request #666</a>\n'  # noqa
            '      </div>\n'
            '      <div class="col-2">\n'
            '        \n'
            '      </div>\n'
            '      <div class="col-2">\n'
            '        NothingToDo\n'
            '      </div>\n'
            '    </div>\n'
            '    <div class="row text-danger">\n'
            '      <div class="col">\n'
            '        details\n'
            '      </div>\n'
            '    </div>\n'
            '  </div>\n'
            '  <div class="bert-e-job pb-2">\n'
            '    <div class="row text-dark">\n'
            '      <div class="col-3">\n'
            '        2016-12-08 14:54:18\n'
            '      </div>\n'
            '      <div class="col-5">\n'
            '        <a href="https://bitbucket.org/foo/bar/commits/123deadbeef12345678901234567890123456789" target="_blank">Webhook for commit 123deadb</a>\n'  # noqa
            '      </div>\n'
            '      <div class="col-2">\n'
            '        \n'
            '      </div>\n'
            '      <div class="col-2">\n'
            '        NothingToDo\n'
            '      </div>\n'
            '    </div>\n'
            '  </div>',
        )

        res = client.get('/')
        data = res.data.decode()
        for exp in expected:
            self.assertIn(exp, data)

    def test_create_branch_api_call(self):
        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            method='POST',
            user=None
        )
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/foo/7.4',
            method='POST',
            user='test_admin'
        )
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            data={'branch_from': 'invalid'},
            method='POST',
            user='test_admin'
        )
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4_',
            method='POST',
            user='test_admin'
        )
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            method='POST',
            user='test_admin'
        )
        self.assertEqual(202, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            data={'branch_from': '12345abcdef'},
            method='POST',
            user='test_admin'
        )
        self.assertEqual(202, resp.status_code)

        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 2)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), CreateBranchJob)
        self.assertEqual(job.settings.branch, 'development/7.4')
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), CreateBranchJob)
        self.assertEqual(job.settings.branch, 'development/7.4')
        self.assertEqual(job.settings.branch_from, '12345abcdef')

    def test_delete_branch_api_call(self):
        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            method='DELETE',
            user=None
        )
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/foo/7.4',
            method='DELETE',
            user='test_admin'
        )
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4_',
            method='DELETE',
            user='test_admin'
        )
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call(
            'gwf/branches/development/7.4',
            method='DELETE',
            user='test_admin'
        )
        self.assertEqual(202, resp.status_code)

        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), DeleteBranchJob)
        self.assertEqual(job.settings.branch, 'development/7.4')

    def test_get_jobs_api_call(self):
        resp = self.handle_api_call('jobs', method='GET', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call('jobs/1', method='GET', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call('jobs/1', method='GET', user='test_user')
        self.assertEqual(404, resp.status_code)

        # put a few tasks in queue
        self.handle_api_call('gwf/queues', user='test_user')
        self.handle_api_call('gwf/queues', user='test_user')
        self.handle_api_call('gwf/queues', user='test_user')

        resp = self.handle_api_call('jobs', method='GET', user='test_user')
        self.assertEqual(200, resp.status_code)

        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 3)
        self.assertTrue(type(resp.json), list)
        self.assertEqual(len(resp.json), 3)
        self.assertEqual(resp.json[0]['type'], 'RebuildQueuesJob')

        first_job_id = resp.json[0]['id']
        resp = self.handle_api_call('jobs/%s' % first_job_id,
                                    method='GET', user='test_user')
        self.assertEqual(200, resp.status_code)
        self.assertEqual(resp.json['type'], 'RebuildQueuesJob')

    def test_rebuild_queues_api_call(self):
        resp = self.handle_api_call('gwf/queues', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call('gwf/queues', user='test_user')
        self.assertEqual(202, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), RebuildQueuesJob)
        resp_json = resp.data.decode()
        self.assertEqual(resp_json, job.as_json())
        self.assertIn('id', resp_json)

    def test_force_merge_queues_api_call(self):
        resp = self.handle_api_call(
            'gwf/queues', method='PATCH', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call(
            'gwf/queues', method='PATCH', user='test_user')
        self.assertEqual(403, resp.status_code)

        resp = self.handle_api_call(
            'gwf/queues', method='PATCH', user='test_admin')
        self.assertEqual(202, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), ForceMergeQueuesJob)
        resp_json = resp.data.decode()
        self.assertEqual(resp_json, job.as_json())
        self.assertIn('id', resp_json)

    def test_delete_queues_api_call(self):
        resp = self.handle_api_call(
            'gwf/queues', method='DELETE', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call(
            'gwf/queues', method='DELETE', user='test_user')
        self.assertEqual(403, resp.status_code)

        resp = self.handle_api_call(
            'gwf/queues', method='DELETE', user='test_admin')
        self.assertEqual(202, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), DeleteQueuesJob)
        resp_json = resp.data.decode()
        self.assertEqual(resp_json, job.as_json())
        self.assertIn('id', resp_json)

    def test_pull_request_api_call(self):
        resp = self.handle_api_call('pull-requests/1', user=None)
        self.assertEqual(401, resp.status_code)

        resp = self.handle_api_call('pull-requests/0', user='test_user')
        self.assertEqual(400, resp.status_code)

        resp = self.handle_api_call('pull-requests/toto', user='test_user')
        self.assertEqual(404, resp.status_code)

        resp = self.handle_api_call('pull-requests/1', user='test_user')
        self.assertEqual(202, resp.status_code)
        self.assertEqual(server.BERTE.task_queue.unfinished_tasks, 1)
        job = server.BERTE.task_queue.get()
        self.assertEqual(type(job), EvalPullRequestJob)
        self.assertEqual(job.settings.pr_id, 1)
        resp_json = resp.data.decode()
        self.assertEqual(resp_json, job.as_json())
        self.assertIn('id', resp_json)

    def test_management_page(self):
        client = self.test_client()
        resp = client.get('/manage')
        self.assertEqual(401, resp.status_code)

        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        self.assertEqual(200, resp.status_code)
        data = resp.data.decode()
        self.assertIn('Admin level tools are deactivated', data)

        client = self.test_client(user='test_admin')
        resp = client.get('/manage')
        self.assertEqual(200, resp.status_code)
        data = resp.data.decode()
        self.assertNotIn('Admin level tools are deactivated', data)

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_create_branch(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        # check normal user does not have access
        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertNotIn('Create a new destination branch', data)
        self.assertNotIn(
            '<form action="/form/CreateBranchForm" '
            'method="post"', data
        )

        client = self.test_client(user='test_admin')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Create a new destination branch', data)
        self.assertIn(
            '<form action="/form/CreateBranchForm" '
            'method="post"', data
        )

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # post should fail csrf from another client
        client2 = self.test_client(user='test_admin_2')
        resp = client2.post('/form/CreateBranchForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/CreateBranchForm', data=dict(
            branch='development/1.0',
            branch_from='1234',
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'POST')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/gwf/branches/development/1.0'
        )

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_delete_branch(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        # check normal user does not have access
        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertNotIn('Delete a destination branch', data)
        self.assertNotIn(
            '<form action="/form/DeleteBranchForm" '
            'method="post"', data
        )

        client = self.test_client(user='test_admin')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Delete a destination branch', data)
        self.assertIn(
            '<form action="/form/DeleteBranchForm" '
            'method="post"', data
        )

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # post should fail csrf from another client
        client2 = self.test_client(user='test_admin_2')
        resp = client2.post('/form/DeleteBranchForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/DeleteBranchForm', data=dict(
            branch='development/1.0',
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'DELETE')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/gwf/branches/development/1.0'
        )

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_rebuild_queues(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Rebuild the queue', data)
        self.assertIn('<form action="/form/RebuildQueuesForm" '
                      'method="post"', data)

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # post should fail csrf from another client
        client2 = self.test_client(user='test_user_2')
        resp = client2.post('/form/RebuildQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/RebuildQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'POST')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/gwf/queues'
        )

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_force_merge_queues(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        # check normal user does not have access
        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertNotIn('Merge the queue', data)
        self.assertNotIn(
            '<form action="/form/ForceMergeQueuesForm" '
            'method="post"', data
        )

        client = self.test_client(user='test_admin')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Merge the queue', data)
        self.assertIn('<form action="/form/ForceMergeQueuesForm" '
                      'method="post"', data)

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # post should fail csrf from another client
        client2 = self.test_client(user='test_admin_2')
        resp = client2.post('/form/ForceMergeQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/ForceMergeQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'PATCH')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/gwf/queues'
        )

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_delete_queues(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        # check normal user does not have access
        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertNotIn('Delete the queue', data)
        self.assertNotIn(
            '<form action="/form/DeleteQueuesForm" '
            'method="post"', data
        )

        client = self.test_client(user='test_admin')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Delete the queue', data)
        self.assertIn('<form action="/form/DeleteQueuesForm" '
                      'method="post"', data)

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # post should fail csrf from another client
        client2 = self.test_client(user='test_admin_2')
        resp = client2.post('/form/DeleteQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/DeleteQueuesForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'DELETE')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/gwf/queues'
        )

    @unittest.mock.patch('bert_e.server.api.base.requests.request')
    def test_management_page_eval_pr(self, mock_request):
        # configure mock
        instance = mock_request.return_value
        instance.status_code = 202

        client = self.test_client(user='test_user')
        resp = client.get('/manage')
        data = resp.data.decode()
        self.assertIn('Evaluate a pull request', data)
        self.assertIn('<form action="/form/EvalPullRequestForm" '
                      'method="post"', data)

        # hard extract session csrf token
        token = re.match(
            '.*<input id="csrf_token" name="csrf_token" '
            'type="hidden" value="([^"]*)">.*', data, re.S).group(1)

        # test invalid data in form
        resp = client.post('/form/EvalPullRequestForm', data=dict(
            csrf_token=token, pr_id='invalid_int'))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        resp = client.post('/form/EvalPullRequestForm', data=dict(
            csrf_token=token, pr_id=0))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        resp = client.post('/form/EvalPullRequestForm', data=dict(
            csrf_token=token))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # post should fail csrf from another client
        client2 = self.test_client(user='test_user_2')
        resp = client2.post('/form/EvalPullRequestForm', data=dict(
            csrf_token=token, pr_id=1))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_not_called()

        # test creation of Job
        resp = client.post('/form/EvalPullRequestForm', data=dict(
            csrf_token=token, pr_id=1))
        self.assertEqual(302, resp.status_code)
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args_list[0][0][0], 'POST')
        self.assertEqual(
            mock_request.call_args_list[0][0][1],
            'http://localhost/api/pull-requests/1'
        )

    def test_bitbucket_addon(self):
        server.BERTE.settings.bitbucket_addon_base_url = ""
        server.BERTE.settings.bitbucket_addon_client_id = ""
        server.BERTE.settings.bitbucket_addon_url = ""

        client = self.test_client()
        resp = client.get('/install-bitbucket-addon')
        self.assertEqual(404, resp.status_code)

        server.BERTE.settings.bitbucket_addon_base_url = "riri"
        server.BERTE.settings.bitbucket_addon_client_id = "fifi"
        server.BERTE.settings.bitbucket_addon_url = "loulou"

        resp = client.get('/install-bitbucket-addon')
        self.assertEqual(200, resp.status_code)


if __name__ == '__main__':
    unittest.main(failfast=True)
