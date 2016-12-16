#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import unittest

from .api.bitbucket import Repository as BitBucketRepository
from .api.bitbucket import Client
from .api.git import Repository as GitRepository


class TestBitbucketApi(unittest.TestCase):

    def setUp(self):
        client = Client('<your login here>',
                        '<your pass here>', '<your mail here>')
        self.bbrepo = BitBucketRepository(client, owner='scality',
                                          repo_slug='test_bert_e')
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
