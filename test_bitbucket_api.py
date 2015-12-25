#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from bitbucket_api import (Client,
                           Repository as BitBucketRepository)
from git_api import Repository as GitRepository


class TestBitbucketApi(unittest.TestCase):

    def setUp(self):
        client = Client('<your login here>',
                                      '<your pass here>', '<your mail here>')
        self.bbrepo = BitBucketRepository(client, owner='scality',
                                          repo_slug='test_wall_e')
        self.bbrepo.delete()
        self.bbrepo.create()
        self.gitrepo = GitRepository(self.bbrepo.get_git_url())
        self.gitrepo.init()

    def test_create_pull_request(self):
        self.gitrepo.create_branch('master2', 'master',
                                   file=True, do_push=True)
        return self.bbrepo.create_pull_request(title='title',
                                               name='name',
                                               source={'branch':
                                                       {'name':
                                                        'master2'}},
                                               destination={'branch':
                                                            {'name':
                                                             'master'}})

    def test_send_comment(self):
        pr = self.test_create_pull_request()
        pr.add_comment('Hello world!')
        pr.add_comment('Hello world2!')
        self.assertEqual(len(pr.get_comments()), 2)

if __name__ == '__main__':
    unittest.main()
