#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import requests
import sys
import unittest

from bitbucket_api import (Repository as BitbucketRepository,
                           Client)
from wall_e import (DestinationBranch, FeatureBranch, WallE)
from wall_e_exceptions import (BranchDoesNotAcceptFeaturesException,
                               CommentAlreadyExistsException,
                               NothingToDoException,
                               AuthorApprovalRequiredException,
                               ConflictException,
                               BranchNameInvalidException,
                               BuildNotStartedException,
                               WallE_Exception,
                               WallE_TemplateException)
from git_api import Repository as GitRepository
from simplecmd import cmd


class TestWallE(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client = Client(cls.args.your_login,
                        cls.args.your_password,
                        cls.args.your_mail)
        cls.bbrepo = BitbucketRepository(client,
                                         owner='scality',
                                         repo_slug=('test_wall_e_%s'
                                                    % cls.args.your_login),
                                         is_private=True)
        try:
            cls.bbrepo.delete()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

        cls.bbrepo.create()
        cls.gitrepo = GitRepository(cls.bbrepo.get_git_url())
        cls.gitrepo.init()
        cls.gitrepo.create_ring_branching_model()

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=['scality_wall-e'],
            file=True):

        self.gitrepo.create_branch(feature_branch, from_branch=from_branch,
                                   file=file)
        return self.bbrepo.create_pull_request(title='title',
                                               name='name',
                                               source={'branch':
                                                       {'name':
                                                        feature_branch}},
                                               destination={'branch':
                                                            {'name':
                                                             from_branch}},
                                               close_source_branch=True,
                                               reviewers=[{'username':
                                                           'scality_wall-e'}],
                                               description='')

    def create_wall_e(self, pr_id):
        self.wall_e = WallE('scality_wall-e', self.args.wall_e_password,
                            'wall_e@scality.com', 'scality',
                            self.bbrepo['repo_slug'], pr_id)

    def handle(self,
               bypass_peer_approval=True,
               bypass_author_approval=True,
               bypass_jira_version_check=True,
               bypass_jira_type_check=True,
               bypass_build_status=True,
               reference_git_repo='',
               no_comment=False,
               interactive=False):
        kwargs = locals()
        del kwargs['self']
        # TODO : move the following logic back to wall-e.py
        try:
            self.wall_e.handle_pull_request(**kwargs)
        except (WallE_Exception, WallE_TemplateException) as e:
            self.wall_e.send_bitbucket_msg(str(e))
            raise

    def test_bugfix_full_merge_manual(self):
        pr = self.create_pr('bugfix/RING-0000', 'development/4.3')
        self.create_wall_e(pr['id'])
        with self.assertRaises(AuthorApprovalRequiredException):
            self.handle(bypass_author_approval=False)
        # PeerApprovalRequiredException and AuthorApprovalRequiredException
        # have the same message, so CommentAlreadyExistsException is used
        with self.assertRaises(CommentAlreadyExistsException):
            self.handle(bypass_author_approval=False)
        self.handle()

    def test_bugfix_full_merge_automatic(self):
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
        self.create_wall_e(pr['id'])
        self.handle()

    def test_handle_manually_twice(self):
        # TODO : remove this test, redundant with test_bugfix_full_merge_manual
        pr = self.create_pr('bugfix/RING-0002', 'development/4.3')
        self.create_wall_e(pr['id'])
        with self.assertRaises(AuthorApprovalRequiredException):
            self.handle(bypass_author_approval=False)
        with self.assertRaises(CommentAlreadyExistsException):
            self.handle(bypass_author_approval=False)

    def test_handle_automatically_twice(self):
        pr = self.create_pr('bugfix/RING-0003', 'development/4.3')
        self.create_wall_e(pr['id'])
        self.handle()
        with self.assertRaises(NothingToDoException):
            self.create_wall_e(pr['id'])
            self.handle()

    def test_refuse_feature_on_maintenance_branch(self):
        pr = self.create_pr('feature/RING-0004', 'development/4.3')
        self.create_wall_e(pr['id'])
        with self.assertRaises(BranchDoesNotAcceptFeaturesException):
            self.handle()

    def test_branch_name_invalid(self):
        dst_branch = 'feature/RING-0005'
        src_branch = 'user/4.3/RING-0005'
        with self.assertRaises(BranchNameInvalidException):
            DestinationBranch(dst_branch)
            FeatureBranch(src_branch)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/4.3',
                             file='toto.txt')
        self.create_wall_e(pr1['id'])
        self.handle()
        pr2 = self.create_pr('improvement/RING-0006', 'development/4.3',
                             file='toto.txt')
        self.create_wall_e(pr2['id'])
        with self.assertRaises(ConflictException):
            self.handle()
        cmd('git merge --abort')

    def test_build_status_not_there_yet(self):
        pr = self.create_pr('bugfix/RING-0007', 'development/4.3')
        self.create_wall_e(pr['id'])
        with self.assertRaises(BuildNotStartedException):
            self.handle(bypass_build_status=False)

    # FIXME: Find a way to test failed build
    def test_build_status_fail(self):
        pass

    # FIXME: Find a way to test build in progress
    def test_build_status_inprogress(self):
        pass

    # FIXME: Find a way to test successful build
    def test_build_status_success(self):
        pass


def main():
    parser = argparse.ArgumentParser(description='Launches Wall-E tests.')
    parser.add_argument('wall_e_password',
                        help='Wall-E\'s password [for Jira and Bitbucket]')
    parser.add_argument('your_login',
                        help='Your Bitbucket login')
    parser.add_argument('your_password',
                        help='Your Bitbucket password')
    parser.add_argument('your_mail',
                        help='Your Bitbucket email address')
    TestWallE.args = parser.parse_args()
    sys.argv = [sys.argv[0]]
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    # loader.testMethodPrefix = "test_conflict"  # uncomment for single test
    unittest.main(failfast=True, testLoader=loader)


if __name__ == '__main__':
    main()
