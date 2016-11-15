import base64
import json
import os
import unittest

from test_server_data import COMMENT_CREATED, COMMIT_STATUS_CREATED
from copy import deepcopy
from collections import OrderedDict

import bitbucket_api
import bitbucket_api_mock

import server
import bert_e

bitbucket_api.Client = bitbucket_api_mock.Client
bitbucket_api.Repository = bitbucket_api_mock.Repository


class TestWebhookListener(unittest.TestCase):
    def handle_post(self, event_type, data):
        os.environ['BERT_E_PWD'] = 'dummy'
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'

        server.APP.config['SETTINGS_DIR'] = '/bert-e'
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
        res = app.get('/')

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

        res = app.get('/')
        assert '{:^10}{:^15}{:^15}'.format(
            '#10', 'SUCCESS', 'FAILED') in res.data

        # Everything is merged, the queue status shouldn't appear anymore
        bert_e.STATUS['merged PRs'].append(10)
        res = app.get('/')

        # PR #10 should appear as merged
        assert '* #10\n' in res.data
        assert 'Merge queue status:' not in res.data

    def test_merge_queue_print(self):
        bert_e.STATUS['merge queue'] = OrderedDict([
            ('4472', [
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
        res = app.get('/')
        for exp in expected:
            assert exp in res.data


if __name__ == '__main__':
    unittest.main(failfast=True)
