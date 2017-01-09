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

import argparse
import logging
import sys
import time
import unittest

from ..api.bitbucket import Repository as BitBucketRepository
from ..api.bitbucket import Client
from ..api.git import Repository as GitRepository
from ..api.git import Branch


def initialize_git_repo(repo, username, usermail):
    """resets the git repo"""
    assert '/ring/' not in repo._url  # This is a security, do not remove
    repo.cmd('git init')
    repo.cmd('git config user.email %s' % usermail)
    repo.cmd('git config user.name %s' % username)
    repo.cmd('touch a')
    repo.cmd('git add a')
    repo.cmd('git commit -m "Initial commit"')
    repo.cmd('git remote add origin ' + repo._url)
    # the following command fail randomly on bitbucket, so retry
    repo.cmd("git push --all origin", retry=3)


class TestBitbucketApi(unittest.TestCase):

    def setUp(self):
        client = Client(self.args.username, self.args.password,
                        'nobody@nowhere.com')
        self.bbrepo = BitBucketRepository(client, owner=self.args.owner,
                                          repo_slug=self.args.slug)
        try:
            self.bbrepo.delete()
            time.sleep(5)
        except Exception:
            pass
        self.bbrepo.create()
        self.gitrepo = GitRepository(self.bbrepo.get_git_url())
        initialize_git_repo(self.gitrepo,
                            self.args.owner,
                            "nobody@nowhere.com")

    def test_create_pull_request_comment_and_task(self):
        Branch(self.gitrepo, 'master2').create(Branch(self.gitrepo, 'master'))
        self.gitrepo.cmd('touch b')
        self.gitrepo.cmd('git add b')
        self.gitrepo.cmd('git commit -m "another commit"')
        # the following command fail randomly on bitbucket, so retry
        self.gitrepo.cmd("git push --all origin", retry=3)
        pr = self.bbrepo.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': 'master2'}},
            destination={'branch': {'name': 'master'}},
            close_source_branch=True,
            description='coucou'
        )

        comment1 = pr.add_comment('Hello world!')
        comment2 = pr.add_comment('Hello world2!')
        self.assertEqual(len(list(pr.get_comments())), 2)

        comment1.add_task('do spam')
        comment1.add_task('do egg')
        comment2.add_task('do bacon')
        self.assertEqual(len(list(pr.get_tasks())), 3)


def main():
    parser = argparse.ArgumentParser(description='Launches bitbucket tests.')
    parser.add_argument('owner',
                        help='Owner of test repository (aka Bitbucket team)')
    parser.add_argument('slug',
                        help='Slug of test repository')
    parser.add_argument('username',
                        help='Bitbucket username')
    parser.add_argument('password',
                        help='Bitbucket password')
    parser.add_argument('tests', nargs='*', help='run only these tests')
    parser.add_argument('--failfast', action='store_true', default=False,
                        help='Return on first failure')
    parser.add_argument('-v', action='store_true', dest='verbose',
                        help='Verbose mode')
    TestBitbucketApi.args = parser.parse_args()

    if TestBitbucketApi.args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

    sys.argv = [sys.argv[0]]
    sys.argv.extend(TestBitbucketApi.args.tests)
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    unittest.main(failfast=TestBitbucketApi.args.failfast, testLoader=loader)


if __name__ == '__main__':
    main()
