#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import sys
import unittest
import requests

import wall_e
from bitbucket_api import (Client,
                           Repository as BitbucketRepository)
from git_api import Repository as GitRepository
from wall_e_exceptions import (AuthorApprovalRequired,
                               BranchDoesNotAcceptFeatures,
                               BranchHistoryMismatch,
                               BranchNameInvalid,
                               BuildInProgress,
                               BuildFailed,
                               BuildNotStarted,
                               CommandNotImplemented,
                               Conflict,
                               HelpMessage,
                               InitMessage,
                               MalformedGitRepo,
                               NothingToDo,
                               ParentPullRequestNotFound,
                               PeerApprovalRequired,
                               StatusReport,
                               SuccessMessage,
                               TesterApprovalRequired)

WALL_E_USERNAME = wall_e.WALL_E_USERNAME
WALL_E_EMAIL = wall_e.WALL_E_EMAIL
EVA_USERNAME = 'scality_eva'
EVA_EMAIL = 'eva.scality@gmail.com'


def initialize_git_repo(repo):
    """resets the git repo"""
    assert '/ring/' not in repo._url  # This is a security, do not remove
    repo.cmd('git init')
    repo.cmd('touch a')
    repo.cmd('git add a')
    repo.cmd('git commit -m "Initial commit"')
    repo.cmd('git remote add origin ' + repo._url)
    for version in ['4.3', '5.1', '6.0', 'trunk']:
        create_branch(repo, 'release/'+version, do_push=False)
        create_branch(repo, 'development/'+version,
                      'release/'+version, file_=True, do_push=False)

        # following commands fail randomly on bitbucket, so retry
        repo.cmd('git push -u origin release/'+version, retry=3)
        repo.cmd('git push -u origin development/'+version, retry=3)


def create_branch(repo, name, from_branch=None, file_=False, do_push=True):
    if from_branch:
        repo.cmd('git checkout '+from_branch)
    repo.cmd('git checkout -b '+name)
    if file_:
        add_file_to_branch(repo, name, file_, do_push)


def add_file_to_branch(repo, branch_name, file_name, do_push=True):
    repo.cmd('git checkout ' + branch_name)
    if file_name is True:
        file_name = 'file_created_on_' + branch_name.replace('/', '_')
    repo.cmd('echo %s >  %s' % (branch_name, file_name))
    repo.cmd('git add ' + file_name)
    repo.cmd('git commit -m "adds %s file on %s"' % (file_name, branch_name))
    if do_push:
        repo.cmd('git pull || exit 0')
        repo.cmd('git push --set-upstream origin '+branch_name)


def rebase_branch(repo, branch_name, on_branch):
    repo.cmd('git checkout ' + branch_name)
    repo.cmd('git rebase ' + on_branch)
    repo.cmd('git push -f')


class QuickTest(unittest.TestCase):
    """Tests which don't need to interact with an external web services"""

    def test_refuse_feature_on_maintenance_branch(self):
        src = wall_e.FeatureBranchName('feature/RING-0004')
        dest = wall_e.DestinationBranchName('development/4.3')
        with self.assertRaises(BranchDoesNotAcceptFeatures):
            src.check_if_should_handle(dest)


class TestWallE(unittest.TestCase):
    bypass_all = [
        'bypass_author_approval',
        'bypass_tester_approval',
        'bypass_peer_approval',
        'bypass_jira_version_check',
        'bypass_jira_type_check',
        'bypass_build_status'
    ]
    bypass_all_but_build_status = [
        'bypass_author_approval',
        'bypass_tester_approval',
        'bypass_peer_approval',
        'bypass_jira_version_check',
        'bypass_jira_type_check'
    ]
    bypass_all_but_author_approval = [
        'bypass_tester_approval',
        'bypass_peer_approval',
        'bypass_jira_version_check',
        'bypass_jira_type_check',
        'bypass_build_status'
    ]
    bypass_jira_checks = [
        'bypass_jira_version_check',
        'bypass_jira_type_check'
    ]

    def setUp(self):
        # repo creator and reviewer
        self.creator = self.args.your_login
        assert self.args.your_login in wall_e.RELEASE_ENGINEERS
        client = Client(self.args.your_login,
                        self.args.your_password,
                        self.args.your_mail)
        self.bbrepo = BitbucketRepository(client,
                                          owner='scality',
                                          repo_slug=('%s_%s'
                                                     % (self.args.repo_prefix,
                                                        self.args.your_login)),
                                          is_private=True,
                                          scm='git')
        try:
            self.bbrepo.delete()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

        self.bbrepo.create()

        # Use Eva as our unprivileged user
        assert EVA_USERNAME not in wall_e.RELEASE_ENGINEERS
        client_eva = Client(EVA_USERNAME,
                            self.args.eva_password,
                            EVA_EMAIL)
        self.bbrepo_eva = BitbucketRepository(
            client_eva,
            owner='scality',
            repo_slug=('%s_%s' % (self.args.repo_prefix,
                                  self.args.your_login)),
        )
        # Wall-E may want to comment manually too
        client_wall_e = Client(WALL_E_USERNAME,
                               self.args.wall_e_password,
                               WALL_E_EMAIL)
        self.bbrepo_wall_e = BitbucketRepository(
            client_wall_e,
            owner='scality',
            repo_slug=('%s_%s' % (self.args.repo_prefix,
                                  self.args.your_login)),
        )
        self.gitrepo = GitRepository(self.bbrepo.get_git_url())
        initialize_git_repo(self.gitrepo)

    def tearDown(self):
        self.gitrepo.delete()

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=None,
            file_=True):
        if reviewers is None:
            reviewers = [self.creator]
        create_branch(self.gitrepo, feature_branch, from_branch=from_branch,
                      file_=file_)
        pr = self.bbrepo_eva.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': feature_branch}},
            destination={'branch': {'name': from_branch}},
            close_source_branch=True,
            reviewers=[{'username': rev} for rev in reviewers],
            description=''
        )
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, InitMessage.code)
        return pr

    def handle(self,
               pull_request_id,
               options=[],
               reference_git_repo='',
               no_comment=False,
               interactive=False,
               backtrace=False,
               build_key=None):

        sys.argv = ["wall-e.py"]
        for option in options:
            sys.argv.append('-o')
            sys.argv.append(option)
        if no_comment:
            sys.argv.append('--no-comment')
        if interactive:
            sys.argv.append('--interactive')
        if backtrace:
            sys.argv.append('--backtrace')
        if build_key:
            sys.argv.append('--build-key')
            sys.argv.append(build_key)
        sys.argv.append('--quiet')

        sys.argv.append('--slug')
        sys.argv.append(self.bbrepo['repo_slug'])
        sys.argv.append(str(pull_request_id))
        sys.argv.append(self.args.wall_e_password)
        return wall_e.main()

    def test_full_merge_manual(self):
        """Test the following conditions:

        - Author approval required,
        - can merge successfully by bypassing all checks,
        - can not merge a second time.

        """
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_jira_checks)
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        # check backtrace mode on the same error, and check same error happens
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        # check success mode
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        # check what happens when trying to do it again
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_refuse_feature_on_maintenance_branch(self):
        pr = self.create_pr('feature/RING-0004', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, BranchDoesNotAcceptFeatures.code)

    def test_branch_name_invalid(self):
        dst_branch = 'feature/RING-0005'
        src_branch = 'user/4.3/RING-0005'
        with self.assertRaises(BranchNameInvalid):
            wall_e.DestinationBranchName(dst_branch)
            wall_e.FeatureBranchName(src_branch)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/4.3',
                             file_='toto.txt')
        pr2 = self.create_pr('improvement/RING-0006', 'development/4.3',
                             file_='toto.txt')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        try:
            self.handle(pr2['id'],
                        options=self.bypass_all,
                        backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`improvement/RING-0006` into `w/4.3/improvement/RING-0006`",
                e.msg)
            self.assertIn(
                "git checkout w/4.3/improvement/RING-0006",
                e.msg)
            self.assertIn(
                "git merge origin/improvement/RING-0006",
                e.msg)
        else:
            self.fail("No conflict detected.")

    def test_approvals(self):
        """Test approvals of author, reviewer and tester."""
        feature_branch = 'bugfix/RING-0007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)

        retcode = self.handle(pr['id'], options=self.bypass_jira_checks)
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # Author adds approval
        pr.approve()
        retcode = self.handle(pr['id'], options=self.bypass_jira_checks)
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # Reviewer adds approval
        pr_peer = self.bbrepo.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer.approve()
        retcode = self.handle(pr['id'], options=self.bypass_jira_checks)
        self.assertEqual(retcode, TesterApprovalRequired.code)

        # Tester adds approval
        pr_tester = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_tester.approve()
        retcode = self.handle(pr['id'], options=[
                              'bypass_jira_version_check',
                              'bypass_jira_type_check',
                              'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_branches_creation_main_pr_not_approved(self):
        """Test if Wall-e creates integration pull-requests when the main
        pull-request isn't approved.

        1. Create feature branch and create an unapproved pull request
        2. Run wall-e on the pull request
        3. Check existence of integration branches

        """
        feature_branch = 'bugfix/RING-0008'
        dst_branch = 'development/4.3'
        pr = self.create_pr(feature_branch, dst_branch)
        retcode = self.handle(pr['id'], options=self.bypass_jira_checks)
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # check existence of integration branches
        for version in ['4.3', '5.1', '6.0']:
            remote = 'w/%s/%s' % (version, feature_branch)
            ret = self.gitrepo.remote_branch_exists(remote)
            self.assertTrue(ret)

        # check absence of a missing branch
        self.assertFalse(self.gitrepo.remote_branch_exists('missing_branch'))

    def test_bypass_all_approvals_through_a_bitbucket_comment(self):
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00045', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_bypass_all_approvals_through_bitbucket_comment_extra_spaces(self):
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00046', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('  @%s  '
                             '   bypass_author_approval  '
                             '     bypass_peer_approval   '
                             ' bypass_tester_approval'
                             '  bypass_build_status'
                             '   bypass_jira_version_check'
                             '   bypass_jira_type_check   ' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_bypass_all_approvals_through_an_incorrect_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00047', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_aproval'  # a p is missing
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_bypass_all_approvals_through_unauthorized_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00048', 'development/4.3')
        pr.add_comment('@%s'  # comment is made by unpriviledged Eva
                       ' bypass_author_approval'
                       ' bypass_peer_approval'
                       ' bypass_tester_approval'
                       ' bypass_build_status'
                       ' bypass_jira_version_check'
                       ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_bypass_all_approvals_through_an_unknown_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00049', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_build_status'
                             ' mmm_never_seen_that_before'  # this is unknown
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_bypass_all_approvals_through_many_comments(self):
        pr = self.create_pr('bugfix/RING-00050', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s bypass_author_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_peer_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_build_status' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_jira_version_check' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'], backtrace=True)

    def test_bypass_all_approvals_through_mix_comments_and_cmdline(self):
        pr = self.create_pr('bugfix/RING-00051', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'], options=[
                        'bypass_build_status',
                        'bypass_jira_version_check'],
                        backtrace=True)

    def test_bypass_author_approval_through_comment(self):
        pr = self.create_pr('bugfix/RING-00052', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        options=self.bypass_all_but_author_approval,
                        backtrace=True)

    def test_bypass_peer_approval_through_comment(self):
        pr = self.create_pr('bugfix/RING-00053', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_peer_approval' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'], options=[
                        'bypass_author_approval',
                        'bypass_tester_approval',
                        'bypass_jira_version_check',
                        'bypass_jira_type_check',
                        'bypass_build_status'],
                        backtrace=True)

    def test_bypass_jira_version_check_through_comment(self):
        pr = self.create_pr('bugfix/RING-00054', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_jira_version_check' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'], options=[
                        'bypass_author_approval',
                        'bypass_tester_approval',
                        'bypass_peer_approval',
                        'bypass_jira_type_check',
                        'bypass_build_status'],
                        backtrace=True)

    def test_bypass_jira_type_check_through_comment(self):
        pr = self.create_pr('bugfix/RING-00055', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'], options=[
                        'bypass_author_approval',
                        'bypass_tester_approval',
                        'bypass_peer_approval',
                        'bypass_jira_version_check',
                        'bypass_build_status'],
                        backtrace=True)

    def test_bypass_build_status_through_comment(self):
        pr = self.create_pr('bugfix/RING-00056', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_build_status' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        options=self.bypass_all_but_build_status,
                        backtrace=True)

    def test_options_lost_in_many_comments(self):
        pr = self.create_pr('bugfix/RING-00057', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        for i in range(5):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_author_approval' % WALL_E_USERNAME)
        for i in range(6):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_peer_approval' % WALL_E_USERNAME)
        for i in range(3):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_build_status' % WALL_E_USERNAME)
        for i in range(22):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_jira_version_check' % WALL_E_USERNAME)
        for i in range(2):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_jira_type_check' % WALL_E_USERNAME)
        for i in range(10):
            pr.add_comment('random comment %s' % i)
        for i in range(10):
            pr.add_comment('@%s bypass_tester_approval' % i)
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)

        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        backtrace=True)

    def test_incorrect_address_when_setting_options_through_comments(self):
        pr = self.create_pr('bugfix/RING-00058', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@toto'  # toto is not Wall-E
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check')
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_options_set_through_deleted_comment(self):
        pr = self.create_pr('bugfix/RING-00059', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_tester_approval'
            ' bypass_build_status'
            ' bypass_jira_version_check'
            ' bypass_jira_type_check' % WALL_E_USERNAME
        )
        comment.delete()
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_bypass_all_approvals_through_bitbucket_comment_extra_chars(self):
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00060', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s:'
                             'bypass_author_approval,  '
                             '     bypass_peer_approval,,   '
                             ' bypass_tester_approval'
                             '  bypass_build_status-bypass_jira_version_check'
                             '   bypass_jira_type_check -   ' %
                             WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        backtrace=True)

    def test_help_command(self):
        pr = self.create_pr('bugfix/RING-00061', 'development/4.3')
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'],
                        backtrace=True)

    def test_help_command_with_inter_comment(self):
        pr = self.create_pr('bugfix/RING-00062', 'development/4.3')
        pr.add_comment('@%s: help' % WALL_E_USERNAME)
        pr.add_comment('an irrelevant comment')
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'],
                        backtrace=True)

    def test_help_command_with_inter_comment_from_wall_e(self):
        pr = self.create_pr('bugfix/RING-00063', 'development/4.3')
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        pr_wall_e = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_wall_e.add_comment('this is my help already')
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_unknown_command(self):
        pr = self.create_pr('bugfix/RING-00064', 'development/4.3')
        pr.add_comment('@%s helpp' % WALL_E_USERNAME)
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_command_args(self):
        pr = self.create_pr('bugfix/RING-00065', 'development/4.3')
        pr.add_comment('@%s help some arguments --hehe' % WALL_E_USERNAME)
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'],
                        backtrace=True)

    def test_main_pr_retrieval(self):
        pr = self.create_pr('bugfix/RING-00066', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)
        # simulate a child pr update
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id']+1,
                        options=self.bypass_all,
                        backtrace=True)

    def test_no_effect_sub_pr_approval(self):
        pr = self.create_pr('bugfix/RING-00067', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)
        pr_child = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        pr_child.approve()
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id']+1,
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_no_effect_sub_pr_options(self):
        pr = self.create_pr('bugfix/RING-00068', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_child_pr_without_parent(self):
        # simulate creation of an integration branch with Wall-E
        create_branch(self.gitrepo, 'w/bugfix/RING-00069',
                      from_branch='development/4.3', file_=True)
        pr = self.bbrepo_wall_e.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': 'w/bugfix/RING-00069'}},
            destination={'branch': {'name': 'development/4.3'}},
            close_source_branch=True,
            reviewers=[{'username': EVA_USERNAME}],
            description=''
        )
        with self.assertRaises(ParentPullRequestNotFound):
            self.handle(pr['id'], backtrace=True)

    def test_status_command(self):
        pr = self.create_pr('bugfix/RING-00070', 'development/4.3')
        pr.add_comment('@%s status' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, StatusReport.code)

        pr.add_comment('@%s unanimity' % WALL_E_USERNAME)
        pr.add_comment('@%s status' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, StatusReport.code)

    def test_wait_option(self):
        pr = self.create_pr('bugfix/RING-00071', 'development/4.3')
        pr.add_comment('@%s wait' % WALL_E_USERNAME)

        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], backtrace=True)

    def test_build_command(self):
        pr = self.create_pr('bugfix/RING-00072', 'development/4.3')
        pr.add_comment('@%s build' % WALL_E_USERNAME)

        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, CommandNotImplemented.code)

    def test_clear_command(self):
        pr = self.create_pr('bugfix/RING-00073', 'development/4.3')
        pr.add_comment('@%s clear' % WALL_E_USERNAME)

        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, CommandNotImplemented.code)

    def test_rebased_feature_branch(self):
        pr = self.create_pr('bugfix/RING-00074', 'development/4.3')
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but_build_status,
                        backtrace=True)

        # create another PR and merge it entirely
        pr2 = self.create_pr('bugfix/RING-00075', 'development/4.3')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        rebase_branch(self.gitrepo, 'bugfix/RING-00075', 'development/4.3')
        with self.assertRaises(SuccessMessage):
            self.handle(pr['id'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_first_integration_branch_manually_updated(self):
        feature_branch = 'bugfix/RING-0076'
        first_integration_branch = 'w/4.3/bugfix/RING-0076'
        pr = self.create_pr(feature_branch, 'development/4.3')
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but_build_status,
                        backtrace=True)

        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('git checkout %s' % first_integration_branch)

        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')

        with self.assertRaises(BranchHistoryMismatch):
            self.handle(pr['id'],
                        options=self.bypass_jira_checks,
                        backtrace=True)

    def test_malformed_git_repo(self):
        """Check that we can detect malformed git repositories."""
        feature_branch = 'bugfix/RING-0077'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        add_file_to_branch(self.gitrepo, 'development/4.3',
                           'file_pushed_without_wall-e.txt', do_push=True)

        with self.assertRaises(MalformedGitRepo):
            self.handle(pr['id'], options=self.bypass_all)

    def set_build_status_on_pr_id(self, pr_id, state,
                                  key='pipeline',
                                  name='Test build status',
                                  url='http://www.scality.com'):
        pr = self.bbrepo_wall_e.get_pull_request(pull_request_id=pr_id)
        self.bbrepo_wall_e.set_build_status(
            revision=pr['source']['commit']['hash'],
            key=key,
            state=state,
            name=name,
            url=url
        )

    def test_build_key_on_main_pr_has_no_effect(self):
        pr = self.create_pr('bugfix/RING-00078', 'development/4.3')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        # create another PR, so that integration PR will have different
        # commits than source PR
        pr2 = self.create_pr('bugfix/RING-00079', 'development/4.3')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        # restart PR number 1 to update it with content of 2
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id'], 'FAILED')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_non_default_build_key_successful(self):
        pr = self.create_pr('bugfix/RING-00080', 'development/4.3')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL', key='pipelin')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL', key='pipelin')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL', key='pipelin')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status,
                              build_key='pipelin')  # note the missing e
        self.assertEqual(retcode, SuccessMessage.code)

    def test_build_status_failed(self):
        pr = self.create_pr('bugfix/RING-00081', 'development/4.3')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr['id']+3, 'FAILED')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildFailed.code)

    def test_build_status_inprogress(self):
        pr = self.create_pr('bugfix/RING-00082', 'development/4.3')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildNotStarted.code)
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all_but_build_status)
        self.assertEqual(retcode, BuildInProgress.code)

    def test_bypass_tester_approval_through_comment(self):
        pr = self.create_pr('bugfix/RING-00078', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)

        retcode = self.handle(pr['id'], options=[
                              'bypass_author_approval',
                              'bypass_peer_approval',
                              'bypass_jira_version_check',
                              'bypass_jira_type_check',
                              'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)


def main():
    parser = argparse.ArgumentParser(description='Launches Wall-E tests.')
    parser.add_argument('wall_e_password',
                        help='Wall-E\'s password [for Jira and Bitbucket]')
    parser.add_argument('eva_password',
                        help='Eva\'s password [for Jira and Bitbucket]')
    parser.add_argument('your_login',
                        help='Your Bitbucket login')
    parser.add_argument('your_password',
                        help='Your Bitbucket password')
    parser.add_argument('your_mail',
                        help='Your Bitbucket email address')
    parser.add_argument('tests', nargs='*', help='run only these tests')
    parser.add_argument('--repo-prefix', default="_test_wall_e",
                        help='Prefix of the test repository')
    parser.add_argument('-v', action='store_true', dest='verbose',
                        help='Verbose mode')
    parser.add_argument('--failfast', action='store_true', default=False,
                        help='Return on first failure')
    TestWallE.args = parser.parse_args()

    if TestWallE.args.your_login == WALL_E_USERNAME:
        print('Cannot use Wall-e as the tester, please use another login.')
        sys.exit(1)

    if TestWallE.args.your_login == EVA_USERNAME:
        print('Cannot use Eva as the tester, please use another login.')
        sys.exit(1)

    if TestWallE.args.your_login not in wall_e.RELEASE_ENGINEERS:
        print('Cannot use %s as the tester, it does not belong to '
              'RELEASE_ENGINEERS.' % TestWallE.args.your_login)
        sys.exit(1)

    if TestWallE.args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        # it is expected that wall-e issues some warning
        # during the tests, only report critical stuff
        logging.basicConfig(level=logging.CRITICAL)

    sys.argv = [sys.argv[0]]
    sys.argv.extend(TestWallE.args.tests)
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    unittest.main(failfast=TestWallE.args.failfast, testLoader=loader)


if __name__ == '__main__':
    main()
