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
        basic_auth = 'Basic ' + base64.b64encode(bytes(
            os.environ['WEBHOOK_LOGIN'] + ":" +
            os.environ['WEBHOOK_PWD'])).decode('ascii')
        resp = app.post('/bitbucket', data=json.dumps(COMMENT_CREATED),
                        headers={'X-Event-Key': 'pullrequest:comment_created',
                                 'Authorization': basic_auth})
        self.assertEqual(500, resp.status_code)
        self.assertEqual([
            '-v',
            '--owner',
            u'scality',
            '--slug',
            u'test_repo',
            '1',
            'dummy'], sys.argv[1:])
        # print resp


if __name__ == '__main__':
    unittest.main(failfast=True)
