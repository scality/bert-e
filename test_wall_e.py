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
                               BuildNotStartedException)
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
                                         is_private=True,
                                         scm='git')
        try:
            cls.bbrepo.delete()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

        cls.bbrepo.create()
        cls.wall_e = WallE('scality_wall-e', cls.args.wall_e_password,
                           'wall_e@scality.com')
        cls.gitrepo = GitRepository(cls.bbrepo.get_git_url())
        cls.gitrepo.init()
        cls.gitrepo.create_ring_branching_model()

    def create_feature_branch_and_pull_request(
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

    def test_bugfix_full_merge_manual(self):
        feature_branch = 'bugfix/RING-0000'
        dst_branch = 'development/4.3'
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch)
        with self.assertRaises(AuthorApprovalRequiredException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)
        # PeerApprovalRequiredException and AuthorApprovalRequiredException
        # have the same message, so CommentAlreadyExistsException is used
        with self.assertRaises(CommentAlreadyExistsException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_author_approval=True,
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)
        self.wall_e.handle_pull_request('scality', self.bbrepo['repo_slug'],
                                        pr['id'],
                                        bypass_peer_approval=True,
                                        bypass_author_approval=True,
                                        bypass_jira_version_check=True,
                                        bypass_jira_type_check=True,
                                        bypass_build_status=True)

    def test_bugfix_full_merge_automatic(self):
        feature_branch = 'bugfix/RING-0001'
        dst_branch = 'development/4.3'
        reviewers = ['scality_wall-e']
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch,
                                                         reviewers=reviewers)
        self.wall_e.handle_pull_request('scality', self.bbrepo['repo_slug'],
                                        pr['id'], bypass_author_approval=True,
                                        bypass_peer_approval=True,
                                        bypass_jira_version_check=True,
                                        bypass_jira_type_check=True,
                                        bypass_build_status=True)

    def test_handle_manually_twice(self):
        feature_branch = 'bugfix/RING-0002'
        dst_branch = 'development/4.3'
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch)
        with self.assertRaises(AuthorApprovalRequiredException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)
        with self.assertRaises(CommentAlreadyExistsException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)

    def test_handle_automatically_twice(self):
        feature_branch = 'bugfix/RING-0003'
        dst_branch = 'development/4.3'
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch)
        self.wall_e.handle_pull_request('scality', self.bbrepo['repo_slug'],
                                        pr['id'], bypass_peer_approval=True,
                                        bypass_author_approval=True,
                                        bypass_jira_version_check=True,
                                        bypass_jira_type_check=True,
                                        bypass_build_status=True)
        with self.assertRaises(NothingToDoException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_peer_approval=True,
                                            bypass_author_approval=True,
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)

    def test_refuse_feature_on_maintenance_branch(self):
        feature_branch = 'feature/RING-0004'
        dst_branch = 'development/4.3'
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch)
        with self.assertRaises(BranchDoesNotAcceptFeaturesException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'], pr['id'],
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True)

    def test_branch_name_invalid(self):
        dst_branch = 'feature/RING-0005'
        src_branch = 'user/4.3/RING-0005'
        with self.assertRaises(BranchNameInvalidException):
            DestinationBranch(dst_branch)
            FeatureBranch(src_branch)

    def test_conflict(self):
        feature_branch = 'bugfix/RING-0006'
        dst_branch = 'development/4.3'
        pr1 = self.create_feature_branch_and_pull_request(feature_branch,
                                                          dst_branch,
                                                          file='toto.txt')
        feature_branch = 'improvement/4.3/RING-0006'
        pr2 = self.create_feature_branch_and_pull_request(feature_branch,
                                                          dst_branch,
                                                          file='toto.txt')
        self.wall_e.handle_pull_request('scality', self.bbrepo['repo_slug'],
                                        pr1['id'], bypass_peer_approval=True,
                                        bypass_author_approval=True,
                                        bypass_jira_version_check=True,
                                        bypass_jira_type_check=True,
                                        bypass_build_status=True)
        with self.assertRaises(ConflictException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'],
                                            pr2['id'],
                                            bypass_peer_approval=True,
                                            bypass_author_approval=True,
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True,
                                            bypass_build_status=True)
        cmd('git merge --abort')

    def test_build_status_not_there_yet(self):
        feature_branch = 'bugfix/RING-0007'
        dst_branch = 'development/4.3'
        pr = self.create_feature_branch_and_pull_request(feature_branch,
                                                         dst_branch)
        with self.assertRaises(BuildNotStartedException):
            self.wall_e.handle_pull_request('scality',
                                            self.bbrepo['repo_slug'],
                                            pr['id'],
                                            bypass_jira_version_check=True,
                                            bypass_jira_type_check=True)

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
    unittest.main(failfast=True)


if __name__ == '__main__':
    main()
