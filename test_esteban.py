import unittest

import esteban
import json
from test_esteban_data import COMMENT_CREATED

import bitbucket_api
import bitbucket_api_mock
import sys
import os
import base64

bitbucket_api.Client = bitbucket_api_mock.Client
bitbucket_api.Repository = bitbucket_api_mock.Repository


class TestWebhookListener(unittest.TestCase):
    def test_comment_added(self):
        os.environ['WALL_E_PWD'] = 'dummy'
        os.environ['WEBHOOK_LOGIN'] = 'dummy'
        os.environ['WEBHOOK_PWD'] = 'dummy'

        app = esteban.APP.test_client()
        worker = esteban.Thread(target=esteban.wall_e_launcher)
        worker.daemon = True
        worker.start()
        basic_auth = 'Basic ' + base64.b64encode(bytes(
            os.environ['WEBHOOK_LOGIN'] + ":" +
            os.environ['WEBHOOK_PWD'])).decode('ascii')
        resp = app.post('/bitbucket', data=json.dumps(COMMENT_CREATED),
                        headers={'X-Event-Key': 'pullrequest:comment_created',
                                 'Authorization': basic_auth})
        self.assertEqual(200, resp.status_code)
        self.assertEqual(esteban.FIFO.unfinished_tasks, 1)
        esteban.FIFO.join()
        self.assertEqual(
            sys.argv[1:],
            ['-v', '--owner', u'scality', '--slug', u'test_repo', '1', 'dummy']
        )
        self.assertEqual(esteban.FIFO.unfinished_tasks, 0)


if __name__ == '__main__':
    unittest.main(failfast=True)
