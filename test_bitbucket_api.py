#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
from bitbucket_api import BitbucketRepo, BitbucketPullRequest, get_bitbucket_client

class TestBitbucketApi(unittest.TestCase):

    def setUp(self):
        bbconn = get_bitbucket_client('rayene_benrayana', '6PyTbDp8CyS4', 'rayene.benrayana@scality.com')
        self.repo = BitbucketRepo(bbconn, 'scality', 'test_wall_e')
        self.repo.delete()
        self.repo.create()
        self.repo.init()
        self.feature_branch = 'bugfix/RING-0000'
        self.development_branch = 'master'
        self.repo.create_branch(self.feature_branch, from_branch=self.development_branch, add_file=True)


    def test_send_comment(self):
        pr = BitbucketPullRequest(self.repo, self.feature_branch, self.development_branch)
        pr.create()
        pr.create_comment('Hello World!')

if __name__ == '__main__':
    unittest.main()


