# Copyright 2016 Scality
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
import unittest
from collections import OrderedDict
from copy import deepcopy

from . import bert_e, server
from .api import bitbucket as bitbucket_api
from .api import bitbucket_mock as bitbucket_api_mock
from .test_server_data import COMMENT_CREATED, COMMIT_STATUS_CREATED

bitbucket_api.Client = bitbucket_api_mock.Client
bitbucket_api.Repository = bitbucket_api_mock.Repository


class TestWebhookListener(unittest.TestCase):
    def handle_post(self, event_type, data):
        os.environ['BERT_E_PWD'] = 'dummy'
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'

        server.APP.config['SETTINGS_FILE'] = '/bert-e/test_owner/test_repo'
        server.APP.config['PULL_REQUEST_BASE_URL'] = \
            'https://bitbucket.org/foo/bar/pull-requests/{pr_id}'
        server.APP.config['COMMIT_BASE_URL'] = \
            'https://bitbucket.org/foo/bar/commits/{commit_id}'
        server.APP.config['REPOSITORY_OWNER'] = \
            data['repository']['owner']['username']
        server.APP.config['REPOSITORY_SLUG'] = data['repository']['name']

        app = server.APP.test_client()
        basic_auth = 'Basic ' + base64.b64encode(bytes(
            os.environ['WEBHOOK_LOGIN'] + ":" +
            os.environ['WEBHOOK_PWD'])).decode('ascii')
        return app.post(
            '/bitbucket', data=json.dumps(data),
            headers={'X-Event-Key': event_type, 'Authorization': basic_auth}
        )

    def test_comment_added(self):
        resp = self.handle_post('pullrequest:comment_created', COMMENT_CREATED)
        self.assertEqual(200, resp.status_code)
        self.assertEqual(server.FIFO.unfinished_tasks, 1)

        job = server.FIFO.get()
        self.assertEqual(job.repo_owner, u'test_owner')
        self.assertEqual(job.repo_slug, u'test_repo')
        self.assertEqual(job.repo_settings, u'/bert-e/test_owner/test_repo')
        self.assertEqual(job.revision, '1')

        server.FIFO.task_done()
        self.assertEqual(server.FIFO.unfinished_tasks, 0)

    def test_build_status_filtered(self):
        data = deepcopy(COMMIT_STATUS_CREATED)
        data[b'commit_status'][b'state'] = b'INPROGRESS'
        resp = self.handle_post('repo:commit_status_created',
                                data)

        self.assertEqual(200, resp.status_code)
        self.assertEqual(server.FIFO.unfinished_tasks, 0)

        data[b'commit_status'][b'state'] = b'SUCCESS'
        resp = self.handle_post('repo:commit_status_created',
                                data)
        self.assertEqual(server.FIFO.unfinished_tasks, 1)

        # consume job
        server.FIFO.get()
        server.FIFO.task_done()

    def test_bert_e_status(self):
        bert_e.STATUS['merge queue'] = OrderedDict([
            ('10', [('4.3', '0033deadbeef'), ('6.0', '13370badf00d')])
        ])

        bert_e.STATUS['merged PRs'] = [1, 2, 3]

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        # Check merged Pull Requests and merge queue status appear in monitor
        # view
        assert 'Recently merged Pull Requests:' in res.data
        assert '* #1\n* #2\n* #3' in res.data
        assert 'Merge queue status:' in res.data
        assert '{:^10}{:^15}{:^15}'.format(
            '#10', 'INPROGRESS', 'INPROGRESS') in res.data

        # Update cache with a successful and a failed build
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('0033deadbeef',
                                                          'FAILED')
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('13370badf00d',
                                                          'SUCCESS')

        res = app.get('/?output=txt')
        assert '{:^10}{:^15}{:^15}'.format(
            '#10', 'SUCCESS', 'FAILED') in res.data

        # Everything is merged, the queue status shouldn't appear anymore
        bert_e.STATUS['merged PRs'].append(10)
        res = app.get('/?output=txt')

        # PR #10 should appear as merged
        assert '* #10\n' in res.data
        assert 'Merge queue status:' not in res.data

    def test_merge_queue_print(self):
        bert_e.STATUS['merge queue'] = OrderedDict([
            (4472, [
                ('6.4', '4472/6.4'),
                ('6.3', '4472/6.3'),
                ('6.2', '4472/6.2')]),
            ('5773', [
                ('6.4', '5773/6.4')]),
            ('6050', [
                ('6.4', '6050/6.4')]),
            ('6086', [
                ('6.4', '6086/6.4'),
                ('6.3.0', '6086/6.3.0'),
                ('6.3', '6086/6.3')]),
            ('5095', [
                ('6.4', '5095/6.4')]),
        ])

        cache = bitbucket_api.BUILD_STATUS_CACHE['pre-merge']
        cache.set('4472/6.4', 'SUCCESSFUL')
        cache.set('4472/6.3', 'SUCCESSFUL')
        cache.set('4472/6.2', 'INPROGRESS')
        cache.set('5773/6.4', 'FAILED')
        cache.set('6050/6.4', 'SUCCESSFUL')
        cache.set('6086/6.4', 'FAILED')
        cache.set('6086/6.3.0', 'SUCCESSFUL')
        cache.set('6086/6.3', 'SUCCESSFUL')
        cache.set('5095/6.4', 'SUCCESSFUL')

        expected = (
            'Merge queue status:',
            '                6.4           6.3.0           6.3            6.2',
            '  #4472     SUCCESSFUL                    SUCCESSFUL'
            '     INPROGRESS',
            '  #5773       FAILED',
            '  #6050     SUCCESSFUL',
            '  #6086       FAILED       SUCCESSFUL     SUCCESSFUL',
            '  #5095     SUCCESSFUL'
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

    def test_current_job_print(self):
        job = server.Job("scality", "example",
                         "456deadbeef12345678901234567890123456789",
                         "2016-12-08 14:54:20.655930", "/dev/null")
        bert_e.STATUS['current job'] = job

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        assert 'Current job: [2016-12-08 14:54:20.655930] scality/example - 456deadbeef12345678901234567890123456789' in res.data # noqa

    def test_pending_jobs_print(self):

        job = server.Job("scality", "example",
                         "123deadbeef12345678901234567890123456789",
                         "2016-12-08 14:54:18.655930", "/dev/null")
        server.FIFO.put(job)
        job = server.Job("scality", "example", "666",
                         "2016-12-08 14:54:19.655930", "/dev/null")
        server.FIFO.put(job)

        expected = (
            '2 pending jobs:',
            '* [2016-12-08 14:54:18.655930] scality/example - 123deadbeef12345678901234567890123456789', # noqa
            '* [2016-12-08 14:54:19.655930] scality/example - 666'
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

        expected = (
            '<b>2 pending jobs:</b><br>',
            '* [2016-12-08 14:54:18.655930] scality/example - <a href="https://bitbucket.org/foo/bar/commits/123deadbeef12345678901234567890123456789">123deadbeef12345678901234567890123456789</a><br>', # noqa
            '* [2016-12-08 14:54:19.655930] scality/example - <a href="https://bitbucket.org/foo/bar/pull-requests/666">666</a><br>' # noqa
        )

        app = server.APP.test_client()
        res = app.get('/')

        for exp in expected:
            assert exp in res.data

    def test_completed_jobs_print(self):

        job = server.Job("scality", "example",
                         "123deadbeef12345678901234567890123456789",
                         "2016-12-08 14:54:18.655930", "/dev/null")
        server.DONE.appendleft((job, "NothingToDo"))
        job = server.Job("scality", "example", "666",
                         "2016-12-08 14:54:19.655930", "/dev/null")
        server.DONE.appendleft((job, "NothingToDo"))

        expected = (
            'Completed jobs:',
            '* [2016-12-08 14:54:19.655930] scality/example - 666 -> NothingToDo', # noqa
            '* [2016-12-08 14:54:18.655930] scality/example - 123deadbeef12345678901234567890123456789 -> NothingToDo' # noqa
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

        expected = (
            '<b>Completed jobs:</b><br>',
            '* [2016-12-08 14:54:19.655930] scality/example - <a href="https://bitbucket.org/foo/bar/pull-requests/666">666</a> -> NothingToDo<br>', # noqa
            '* [2016-12-08 14:54:18.655930] scality/example - <a href="https://bitbucket.org/foo/bar/commits/123deadbeef12345678901234567890123456789">123deadbeef12345678901234567890123456789</a> -> NothingToDo<br>' # noqa
        )

        app = server.APP.test_client()
        res = app.get('/')

        for exp in expected:
            assert exp in res.data


if __name__ == '__main__':
    unittest.main(failfast=True)
