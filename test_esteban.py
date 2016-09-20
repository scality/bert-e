import unittest

import esteban
import json
from test_esteban_data import COMMENT_CREATED, COMMIT_STATUS_CREATED

import bitbucket_api
import bitbucket_api_mock
import os
import base64

bitbucket_api.Client = bitbucket_api_mock.Client
bitbucket_api.Repository = bitbucket_api_mock.Repository


class TestWebhookListener(unittest.TestCase):
    def handle_post(self, event_type, data):
        os.environ['WALL_E_PWD'] = 'dummy'
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'

        app = esteban.APP.test_client()
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
        self.assertEqual(esteban.FIFO.unfinished_tasks, 1)

        job = esteban.FIFO.get()
        self.assertEqual(job.repo_owner, u'scality')
        self.assertEqual(job.repo_slug, u'test_repo')
        self.assertEqual(job.revision, '1')

        esteban.FIFO.task_done()
        self.assertEqual(esteban.FIFO.unfinished_tasks, 0)

    def test_build_status_filtered(self):
        resp = self.handle_post('repo:commit_status_created',
                                COMMIT_STATUS_CREATED)

        self.assertEqual(200, resp.status_code)
        self.assertEqual(esteban.FIFO.unfinished_tasks, 0)


if __name__ == '__main__':
    unittest.main(failfast=True)
