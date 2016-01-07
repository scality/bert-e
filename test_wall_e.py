#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import requests
import sys
import unittest

from bitbucket_api import (Repository as BitbucketRepository,
                           Client)
import wall_e
from wall_e_exceptions import (BranchDoesNotAcceptFeaturesException,
                               CommentAlreadyExistsException,
                               NothingToDoException,
                               AuthorApprovalRequiredException,
                               ConflictException,
                               BranchNameInvalidException)
from git_api import Repository as GitRepository
from simplecmd import cmd

WALL_E_USERNAME = wall_e.WALL_E_USERNAME


def initialize_git_repo(repo):
    """resets the git repo"""
    assert '/ring/' not in repo._url  # This is a security, do not remove
    cmd('git init')
    cmd('touch a')
    cmd('git add a')
    cmd('git commit -m "Initial commit"')
    cmd('git remote add origin ' + repo._url)
    # cmd('git push --set-upstream origin master')
    for version in ['4.3', '5.1', '6.0', 'trunk']:
        create_branch('release/'+version, do_push=False)
        create_branch('development/'+version,
                      'release/'+version, file_=True, do_push=False)

        repo.push_everything()


def create_branch(name, from_branch=None, file_=False, do_push=True):
    if from_branch:
        cmd('git checkout '+from_branch)
    cmd('git checkout -b '+name)
    if file_:
        if file_ is True:
            file_ = name.replace('/', '-')
        cmd('echo %s >  a.%s' % (name, file_))
        cmd('git add a.'+file_)
        cmd('git commit -m "commit %s"' % file_)
    if do_push:
        cmd('git push --set-upstream origin '+name)


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
        cls.gitrepo = GitRepository(cls.bbrepo.get_git_url())
        initialize_git_repo(cls.gitrepo)

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=[WALL_E_USERNAME],
            file_=True):

        create_branch(feature_branch, from_branch=from_branch, file_=file_)
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
                                                           WALL_E_USERNAME}],
                                               description='')

    def handle(self,
               pull_request_id,
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
        sys.argv = ["wall-e.py"]
        if bypass_author_approval:
            sys.argv.append('--bypass_author_approval')
        if bypass_peer_approval:
            sys.argv.append('--bypass_peer_approval')
        if bypass_jira_version_check:
            sys.argv.append('--bypass_jira_version_check')
        if bypass_jira_type_check:
            sys.argv.append('--bypass_jira_type_check')
        if bypass_build_status:
            sys.argv.append('--bypass_build_status')
        if no_comment:
            sys.argv.append('--no_comment')
        if interactive:
            sys.argv.append('--interactive')

        sys.argv.append('--slug')
        sys.argv.append(self.bbrepo['repo_slug'])
        sys.argv.append(str(pull_request_id))
        sys.argv.append(self.args.wall_e_password)
        wall_e.main()

    def test_bugfix_full_merge_manual(self):
        pr = self.create_pr('bugfix/RING-0000', 'development/4.3')
        with self.assertRaises(AuthorApprovalRequiredException):
            self.handle(pr['id'], bypass_author_approval=False)
        # PeerApprovalRequiredException and AuthorApprovalRequiredException
        # have the same message, so CommentAlreadyExistsException is used
        with self.assertRaises(CommentAlreadyExistsException):
            self.handle(pr['id'], bypass_author_approval=False)
        self.handle(pr['id'])

    def test_bugfix_full_merge_automatic(self):
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
        self.handle(pr['id'])

    def test_handle_manually_twice(self):
        # TODO : remove this test, redundant with test_bugfix_full_merge_manual
        pr = self.create_pr('bugfix/RING-0002', 'development/4.3')
        with self.assertRaises(AuthorApprovalRequiredException):
            self.handle(pr['id'], bypass_author_approval=False)
        with self.assertRaises(CommentAlreadyExistsException):
            self.handle(pr['id'], bypass_author_approval=False)

    def test_handle_automatically_twice(self):
        pr = self.create_pr('bugfix/RING-0003', 'development/4.3')
        self.handle(pr['id'])
        with self.assertRaises(NothingToDoException):
            self.handle(pr['id'])

    def test_refuse_feature_on_maintenance_branch(self):
        pr = self.create_pr('feature/RING-0004', 'development/4.3')
        with self.assertRaises(BranchDoesNotAcceptFeaturesException):
            self.handle(pr['id'])

    def test_branch_name_invalid(self):
        dst_branch = 'feature/RING-0005'
        src_branch = 'user/4.3/RING-0005'
        with self.assertRaises(BranchNameInvalidException):
            wall_e.DestinationBranch(dst_branch)
            wall_e.FeatureBranch(src_branch)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/4.3',
                             file_='toto.txt')
        self.handle(pr1['id'])
        pr2 = self.create_pr('improvement/RING-0006', 'development/4.3',
                             file_='toto.txt')
        with self.assertRaises(ConflictException):
            self.handle(pr2['id'])
        cmd('git merge --abort')

    # FIXME: Find a way to test not started build
    def test_build_status_not_there_yet(self):
        pass

    # FIXME: Find a way to test failed build
    def test_build_status_fail(self):
        pass

    # FIXME: Find a way to test build in progress
    def test_build_status_inprogress(self):
        pass

    # FIXME: Find a way to test successful build
    def test_build_status_success(self):
        pass

    def test_bypass_all_approvals_through_a_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00045', 'development/4.3')
        pr.add_comment('wall-e'
                       ' --bypass_author_approval'
                       ' --bypass_peer_approval'
                       ' --bypass_build_status'
                       ' --bypass_jira_version_check'
                       ' --bypass_jira_type_check')
        self.handle(
            pr['id'],
            bypass_author_approval=False,
            bypass_peer_approval=False,
            bypass_build_status=False,
            bypass_jira_type_check=False,
            bypass_jira_version_check=False)


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

    if TestWallE.args.your_login == WALL_E_USERNAME:
        print('Cannot use Wall-e as the tester, please use another login.')
        sys.exit(1)

    sys.argv = [sys.argv[0]]
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    # loader.testMethodPrefix = "test_conflict"  # uncomment for single test
    unittest.main(failfast=True, testLoader=loader)


if __name__ == '__main__':
    main()
