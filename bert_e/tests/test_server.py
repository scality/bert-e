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
from datetime import datetime

from .. import bert_e, server
from ..api import bitbucket as bitbucket_api
from .mocks import bitbucket as bitbucket_api_mock
from .test_server_data import COMMENT_CREATED, COMMIT_STATUS_CREATED

bitbucket_api.Client = bitbucket_api_mock.Client
bitbucket_api.Repository = bitbucket_api_mock.Repository


class TestWebhookListener(unittest.TestCase):
    def setUp(self):
        server.APP.config['SETTINGS_FILE'] = '/bert-e/test_owner/test_repo'
        server.APP.config['PULL_REQUEST_BASE_URL'] = \
            'https://bitbucket.org/foo/bar/pull-requests/{pr_id}'
        server.APP.config['COMMIT_BASE_URL'] = \
            'https://bitbucket.org/foo/bar/commits/{commit_id}'
        server.APP.config['REPOSITORY_OWNER'] = 'test_user'
        server.APP.config['REPOSITORY_SLUG'] = 'test_repo'

    def handle_post(self, event_type, data):
        os.environ['BERT_E_PWD'] = 'dummy'
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'

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
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('0033deadbeef',
                                                          'INPROGRESS')
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('0033deadbeef-build',
                                                          'fakeurl')

        bert_e.STATUS['merged PRs'] = [
            {'id': 1, 'merge_time': datetime(2016, 12, 9, 14, 54, 20, 123456)},
            {'id': 2, 'merge_time': datetime(2016, 12, 9, 14, 54, 21, 123456)},
            {'id': 3, 'merge_time': datetime(2016, 12, 8, 14, 54, 22, 123456)}
        ]

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        # Check merged Pull Requests and merge queue status appear in monitor
        # view
        assert 'Recently merged pull requests:' in res.data
        assert '* [2016-12-09 14:54:20] - #1\n' in res.data
        assert '* [2016-12-09 14:54:21] - #2\n' in res.data
        assert '* [2016-12-08 14:54:22] - #3\n' in res.data
        assert 'Merge queue status:' in res.data
        assert '   #10       NOTSTARTED     INPROGRESS  ' in res.data

        res = app.get('/')
        assert 'Recently merged pull requests:' in res.data
        assert '<li>[2016-12-09 14:54:20] - <a href="https://bitbucket.or' \
               'g/foo/bar/pull-requests/1">#1</a></li>' in res.data
        assert '<li>[2016-12-09 14:54:21] - <a href="https://bitbucket.or' \
               'g/foo/bar/pull-requests/2">#2</a></li>' in res.data
        assert '<li>[2016-12-08 14:54:22] - <a href="https://bitbucket.or' \
               'g/foo/bar/pull-requests/3">#3</a></li>' in res.data
        assert 'Merge queue status:' in res.data
        assert '<td><a href="https://bitbucket.org/foo/bar/pull-requests/' \
               '10">#10</a></td><td>NOTSTARTED</td><td><a href="fakeurl">' \
               'INPROGRESS</a></td>' in res.data

        # Update cache with a successful and a failed build
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('0033deadbeef',
                                                          'FAILED')
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('0033deadbeef-build',
                                                          'url2')
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('13370badf00d',
                                                          'SUCCESS')
        bitbucket_api.BUILD_STATUS_CACHE['pre-merge'].set('13370badf00d-build',
                                                          'url3')

        res = app.get('/?output=txt')
        assert '   #10        SUCCESS         FAILED    ' in res.data

        res = app.get('/')

        assert '<td><a href="https://bitbucket.org/foo/bar/pull-requests/' \
               '10">#10</a></td><td><a href="url3">SUCCESS</a></td><td><a' \
               ' href="url2">FAILED</a></td>' in res.data

        # Everything is merged, the queue status shouldn't appear anymore
        bert_e.STATUS['merged PRs'].append({
            'id': 10,
            'merge_time': datetime(2016, 12, 9, 14, 54, 20, 123456)
        })
        res = app.get('/?output=txt')

        # PR #10 should appear as merged
        assert '* [2016-12-09 14:54:20] - #10' in res.data
        assert 'Merge queue status:' not in res.data

        res = app.get('/')
        assert '<li>[2016-12-09 14:54:20] - <a href="https://bitbucket.or' \
               'g/foo/bar/pull-requests/10">#10</a></li>' in res.data
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
        cache.set('4472/6.4-build', '4472/6.4_url')
        cache.set('4472/6.3', 'SUCCESSFUL')
        cache.set('4472/6.3-build', '4472/6.3_url')
        cache.set('4472/6.2', 'INPROGRESS')
        cache.set('4472/6.2-build', '4472/6.2_url')
        cache.set('5773/6.4', 'FAILED')
        cache.set('5773/6.4-build', '5773/6.4_url')
        cache.set('6050/6.4', 'SUCCESSFUL')
        cache.set('6050/6.4-build', '6050/6.4_url')
        cache.set('6086/6.4', 'FAILED')
        cache.set('6086/6.4-build', '6086/6.4_url')
        cache.set('6086/6.3.0', 'SUCCESSFUL')
        cache.set('6086/6.3.0-build', '6086/6.3.0_url')
        cache.set('6086/6.3', 'SUCCESSFUL')
        cache.set('6086/6.3-build', '6086/6.3_url')
        cache.set('5095/6.4', 'SUCCESSFUL')
        cache.set('5095/6.4-build', '5095/6.4_urltoto')

        expected = (
            'Merge queue status:',
            '                6.4           6.3.0           6.3            6.2',
            '  #4472      SUCCESSFUL                    SUCCESSFUL     INPROGRESS  \n', # noqa
            '  #5773        FAILED                                                 \n', # noqa
            '  #6050      SUCCESSFUL                                               \n', # noqa
            '  #6086        FAILED       SUCCESSFUL     SUCCESSFUL                 \n', # noqa
            '  #5095      SUCCESSFUL                                               \n'  # noqa
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

        expected = (
            '<h3>Merge queue status:</h3>\n'
            '<table border="1" cellpadding="10">\n'
            '<tr align="center">\n'
            '<td></td>\n'
            '<td>6.4</td>\n'
            '<td>6.3.0</td>\n'
            '<td>6.3</td>\n'
            '<td>6.2</td>\n'
            '</tr>\n'
            '<tr align="center">\n'
            '<td><a href="https://bitbucket.org/foo/bar/pull-requests/4472">'
            '#4472</a></td>\n'
            '<td><a href="4472/6.4_url">SUCCESSFUL</a></td>\n'
            '<td></td>\n'
            '<td><a href="4472/6.3_url">SUCCESSFUL</a></td>\n'
            '<td><a href="4472/6.2_url">INPROGRESS</a></td>\n'
            '</tr>\n'
            '<tr align="center">\n'
            '<td><a href="https://bitbucket.org/foo/bar/pull-requests/5773">'
            '#5773</a></td>\n'
            '<td><a href="5773/6.4_url">FAILED</a></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '</tr>\n'
            '<tr align="center">\n'
            '<td><a href="https://bitbucket.org/foo/bar/pull-requests/6050">'
            '#6050</a></td>\n'
            '<td><a href="6050/6.4_url">SUCCESSFUL</a></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '</tr>\n'
            '<tr align="center">\n'
            '<td><a href="https://bitbucket.org/foo/bar/pull-requests/6086">'
            '#6086</a></td>\n'
            '<td><a href="6086/6.4_url">FAILED</a></td>\n'
            '<td><a href="6086/6.3.0_url">SUCCESSFUL</a></td>\n'
            '<td><a href="6086/6.3_url">SUCCESSFUL</a></td>\n'
            '<td></td>\n'
            '</tr>\n'
            '<tr align="center">\n'
            '<td><a href="https://bitbucket.org/foo/bar/pull-requests/5095">'
            '#5095</a></td>\n'
            '<td><a href="5095/6.4_urltoto">SUCCESSFUL</a></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '<td></td>\n'
            '</tr>\n'
            '</table>\n'
        )

        res = app.get('/')

        for exp in expected:
            assert exp in res.data

    def test_current_job_print(self):
        job = server.Job("test_owner", "test_repo",
                         "456deadbeef12345678901234567890123456789",
                         datetime(2016, 12, 8, 14, 54, 20, 123456),
                         "/dev/null")
        bert_e.STATUS['current job'] = job

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        assert 'Current job: [2016-12-08 14:54:20]' \
               ' - 456deadbeef12345678901234567890123456789' in res.data

    def test_pending_jobs_print(self):

        job = server.Job("test_owner", "test_repo",
                         "123deadbeef12345678901234567890123456789",
                         datetime(2016, 12, 8, 14, 54, 18, 123456),
                         "/dev/null")
        server.FIFO.put(job)
        job = server.Job("test_owner", "test_repo", "666",
                         datetime(2016, 12, 8, 14, 54, 19, 123456),
                         "/dev/null")
        server.FIFO.put(job)

        expected = (
            '2 pending jobs:',
            '* [2016-12-08 14:54:18] - 123deadbeef'
            '12345678901234567890123456789',
            '* [2016-12-08 14:54:19] - 666'
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

        expected = (
            '<h3>2 pending jobs:</h3>',
            '<li>[2016-12-08 14:54:18] - <a href='
            '"https://bitbucket.org/foo/bar/commits/123deadbeef123456789'
            '01234567890123456789">123deadbeef12345678901234567890123456'
            '789</a></li>',
            '<li>[2016-12-08 14:54:19] - <a href='
            '"https://bitbucket.org/foo/bar/pull-requests/666">666</a></'
            'li>'
        )

        res = app.get('/')

        for exp in expected:
            assert exp in res.data

    def test_completed_jobs_print(self):

        job = server.Job("test_owner", "test_repo",
                         "123deadbeef12345678901234567890123456789",
                         datetime(2016, 12, 8, 14, 54, 18, 123456),
                         "/dev/null")
        server.DONE.appendleft({
            'job': job, 'status': "NothingToDo", 'details': None})
        job = server.Job("test_owner", "test_repo", "666",
                         datetime(2016, 12, 8, 14, 54, 19, 123456),
                         "/dev/null")
        server.DONE.appendleft({
            'job': job, 'status': "NothingToDo", 'details': "details"})

        expected = (
            'Completed jobs:',
            '* [2016-12-08 14:54:19] - '
            '666 -> NothingToDo\ndetails',
            '* [2016-12-08 14:54:18] - '
            '123deadbeef12345678901234567890123456789 -> NothingToDo'
        )

        app = server.APP.test_client()
        res = app.get('/?output=txt')

        for exp in expected:
            assert exp in res.data

        expected = (
            '<h3>Completed jobs:</h3>',
            '<li>[2016-12-08 14:54:19] - <a href="https://bitbucket.org/f'
            'oo/bar/pull-requests/666">666</a> -> NothingToDo<p>details</'
            'p></li>',
            '<li>[2016-12-08 14:54:18] - <a href="https://bitbucket.org/f'
            'oo/bar/commits/123deadbeef12345678901234567890123456789">123'
            'deadbeef12345678901234567890123456789</a> -> NothingToDo</li>'
        )

        res = app.get('/')

        for exp in expected:
            assert exp in res.data


if __name__ == '__main__':
    unittest.main(failfast=True)
