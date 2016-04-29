#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import sys
import unittest
import requests
from hashlib import md5
from collections import OrderedDict

import bitbucket_api
import bitbucket_api_mock
import jira_api
import jira_api_mock
import wall_e
from git_api import Repository as GitRepository
from wall_e_exceptions import (AfterPullRequest,
                               AuthorApprovalRequired,
                               BranchHistoryMismatch,
                               BranchNameInvalid,
                               BuildInProgress,
                               BuildFailed,
                               BuildNotStarted,
                               CommandNotImplemented,
                               Conflict,
                               DevBranchDoesNotExist,
                               DevBranchesNotSelfContained,
                               DeprecatedStabilizationBranch,
                               HelpMessage,
                               IncompatibleSourceBranchPrefix,
                               IntegrationPullRequestsCreated,
                               InitMessage,
                               MissingJiraId,
                               NotEnoughCredentials,
                               NothingToDo,
                               NotMyJob,
                               ParentPullRequestNotFound,
                               PeerApprovalRequired,
                               StatusReport,
                               PullRequestSkewDetected,
                               SuccessMessage,
                               TesterApprovalRequired,
                               UnanimityApprovalRequired,
                               UnknownCommand,
                               UnrecognizedBranchPattern,
                               UnsupportedMultipleStabBranches,
                               VersionMismatch)

WALL_E_USERNAME = wall_e.WALL_E_USERNAME
WALL_E_EMAIL = wall_e.WALL_E_EMAIL
EVA_USERNAME = 'scality_eva'
EVA_EMAIL = 'eva.scality@gmail.com'


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
    for major, minor, micro in [(4, 3, 18), (5, 1, 4), (6, 0, 0)]:
        major_minor = "%s.%s" % (major, minor)
        full_version = "%s.%s.%s" % (major, minor, micro)
        create_branch(repo, 'release/'+major_minor, do_push=False)
        create_branch(repo, 'stabilization/'+full_version,
                      'release/'+major_minor, file_=True, do_push=False)
        create_branch(repo, 'development/'+major_minor,
                      'stabilization/'+full_version, file_=True, do_push=False)
        if major != 6:
            repo.cmd('git tag %s.%s.%s' % (major, minor, micro-1))

    repo.cmd('git branch -d master')
    # the following command fail randomly on bitbucket, so retry
    repo.cmd("git push --all origin", retry=3)
    repo.cmd("git push --tags", retry=3)


def create_branch(repo, name, from_branch=None, file_=False, do_push=True):
    if from_branch:
        repo.cmd('git checkout '+from_branch)
    repo.cmd('git checkout -b %s' % name)
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

    def feature_branch(self, name):
        return wall_e.FeatureBranch(None, name)

    def test_feature_branch_names(self):
        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('user/4.3/RING-0005')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('RING-0001-my-fix')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('my-fix')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('origin/feature/RING-0001')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('/feature/RING-0001')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('toto/RING-0005')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('release/4.3')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('feature')

        with self.assertRaises(BranchNameInvalid):
            self.feature_branch('feature/')

        # valid names
        self.feature_branch('feature/RING-0005')
        self.feature_branch('improvement/RING-1234')
        self.feature_branch('bugfix/RING-1234')

        src = self.feature_branch('project/RING-0005')
        self.assertEqual(src.jira_issue_key, 'RING-0005')
        self.assertEqual(src.jira_project, 'RING')

        src = self.feature_branch('feature/PROJECT-05-some-text_here')
        self.assertEqual(src.jira_issue_key, 'PROJECT-05')
        self.assertEqual(src.jira_project, 'PROJECT')

        src = self.feature_branch('feature/some-text_here')
        self.assertIsNone(src.jira_issue_key)
        self.assertIsNone(src.jira_project)

    def test_destination_branch_names(self):

        with self.assertRaises(BranchNameInvalid):
            wall_e.DevelopmentBranch(
                repo=None,
                name='feature-RING-0005')

        # valid names
        wall_e.DevelopmentBranch(
            repo=None,
            name='development/4.3')
        wall_e.DevelopmentBranch(
            repo=None,
            name='development/5.1')
        wall_e.DevelopmentBranch(
            repo=None,
            name='development/6.0')

    def finalize_cascade(self, branches, tags, destination, fixver):
        c = wall_e.BranchCascade()

        all_branches = [
            wall_e.branch_factory(FakeGitRepo(), branch['name'])
            for branch in branches.values()]
        expected_dest = [
            wall_e.branch_factory(FakeGitRepo(), branch['name'])
            for branch in branches.values() if not branch['ignore']]
        expected_ignored = [
            branch['name']
            for branch in branches.values() if branch['ignore']]
        expected_ignored.sort()

        for branch in all_branches:
            c.add_branch(branch)

        for tag in tags:
            c.update_micro(tag)

        c.finalize(wall_e.branch_factory(FakeGitRepo(), destination))

        self.assertEqual(c.destination_branches, expected_dest)
        self.assertEqual(c.ignored_branches, expected_ignored)
        self.assertEqual(c.target_versions, fixver)
        return c

    def test_branch_cascade_from_master(self):
        destination = 'master'
        branches = OrderedDict({
            1: {'name': 'master',               'ignore': True}
        })
        tags = []
        fixver = []
        with self.assertRaises(UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_from_dev_with_master(self):
        destination = 'development/1.0'
        branches = OrderedDict({
            1: {'name': 'master',               'ignore': True},
            2: {'name': 'development/1.0',      'ignore': True}
        })
        tags = []
        fixver = []
        with self.assertRaises(UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_first_stab(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/4.3',      'ignore': False},
            3: {'name': 'development/5.1',      'ignore': False},
            4: {'name': 'stabilization/5.1.4',  'ignore': True},
            5: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1']
        fixver = ['4.3.18', '5.1.5', '6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_last_stab(self):
        destination = 'stabilization/5.1.4'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3',      'ignore': True},
            3: {'name': 'stabilization/5.1.4',  'ignore': False},
            4: {'name': 'development/5.1',      'ignore': False},
            5: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_t', '5.1.3', '5.1.4_rc1', '6.0.0']
        fixver = ['5.1.4', '6.0.1']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_first_dev(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3',      'ignore': False},
            3: {'name': 'stabilization/5.1.4',  'ignore': True},
            4: {'name': 'development/5.1',      'ignore': False},
            5: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['4.3.18_rc1', '5.1.3', '5.1.4_rc1', '4.3.16', '4.3.17']
        fixver = ['4.3.19', '5.1.5', '6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_middle_dev(self):
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3',      'ignore': True},
            3: {'name': 'stabilization/5.1.4',  'ignore': True},
            4: {'name': 'development/5.1',      'ignore': False},
            5: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1']
        fixver = ['5.1.5', '6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_last_dev(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3',      'ignore': True},
            3: {'name': 'stabilization/5.1.4',  'ignore': True},
            4: {'name': 'development/5.1',      'ignore': True},
            5: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1']
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_incorrect_stab_name(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/6.0',    'ignore': True},
            2: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['6.0.0']
        fixver = ['6.0.1']
        with self.assertRaises(UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_targetting_incorrect_stab_name(self):
        destination = 'stabilization/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/6.0',    'ignore': False},
            2: {'name': 'development/6.0',      'ignore': False}
        })
        tags = ['6.0.0']
        fixver = ['6.0.1']
        with self.assertRaises(UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_dangling_stab(self):
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/5.1',      'ignore': False}
        })
        tags = ['4.3.17', '5.1.3']
        fixver = ['5.1.4']
        with self.assertRaises(DevBranchDoesNotExist):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_targetting_dangling_stab(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/5.1',      'ignore': False}
        })
        tags = ['4.3.17', '5.1.3']
        fixver = ['4.3.18', '5.1.4']
        with self.assertRaises(DevBranchDoesNotExist):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_multi_stab_branches(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.17', 'ignore': True},
            2: {'name': 'stabilization/4.3.18', 'ignore': False},
            3: {'name': 'development/4.3',      'ignore': False}
        })
        tags = []
        fixver = []
        with self.assertRaises(UnsupportedMultipleStabBranches):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_invalid_dev_branch(self):
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17',   'ignore': False}
        })
        tags = []
        fixver = []
        with self.assertRaises(UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_tags_without_stabilization(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'development/5.1',      'ignore': True},
            2: {'name': 'development/6.0',      'ignore': False}
        })

        tags = []
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['toto']
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['toto', '6.0.2']
        fixver = ['6.0.3']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.0.15_rc1']
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.0.15_rc1', '4.2.1', '6.0.0']
        fixver = ['6.0.1']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.0.15_rc1', '6.0.0', '5.1.4', '6.0.1']
        fixver = ['6.0.2']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.0.4000']
        fixver = ['6.0.4001']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.0.4000', '6.0.3999']
        fixver = ['6.0.4001']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_tags_with_stabilization(self):
        destination = 'stabilization/6.1.5'
        branches = OrderedDict({
            1: {'name': 'stabilization/6.1.5',  'ignore': False},
            2: {'name': 'development/6.1',      'ignore': False}
        })

        tags = []
        fixver = ['6.1.5']
        c = self.finalize_cascade(branches, tags, destination, fixver)
        with self.assertRaises(VersionMismatch):
            c.validate()

        tags = ['6.1.4']
        fixver = ['6.1.5']
        c = self.finalize_cascade(branches, tags, destination, fixver)
        self.assertEqual(
            c._cascade[(6, 1)][wall_e.DevelopmentBranch].micro, 6)
        self.assertEqual(
            c._cascade[(6, 1)][wall_e.StabilizationBranch].micro, 5)

        tags = ['6.1.5']
        fixver = []
        with self.assertRaises(DeprecatedStabilizationBranch):
            self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.1.6']
        fixver = []
        with self.assertRaises(DeprecatedStabilizationBranch):
            self.finalize_cascade(branches, tags, destination, fixver)


class FakeGitRepo:
    def includes_commit(self, commit):
        return True

    def cmd(self, command):
        return True


class TestWallE(unittest.TestCase):
    bypass_all = [
        'bypass_author_approval',
        'bypass_build_status',
        'bypass_incompatible_branch',
        'bypass_jira_check',
        'bypass_peer_approval',
        'bypass_tester_approval'
    ]

    def bypass_all_but(self, exceptions):
        assert isinstance(exceptions, list)
        bypasses = list(self.bypass_all)
        for exception in exceptions:
            bypasses.remove(exception)
        return bypasses

    def setUp(self):
        # repo creator and reviewer
        self.creator = self.args.your_login
        assert self.args.your_login in wall_e.SETTINGS['ring']['admins']
        client = bitbucket_api.Client(
            self.args.your_login,
            self.args.your_password,
            self.args.your_mail)
        self.bbrepo = bitbucket_api.Repository(
            client,
            owner='scality',
            repo_slug=('%s_%s' % (self.args.repo_prefix,
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
        assert EVA_USERNAME not in wall_e.SETTINGS['ring']['admins']
        client_eva = bitbucket_api.Client(
            EVA_USERNAME,
            self.args.eva_password,
            EVA_EMAIL)
        self.bbrepo_eva = bitbucket_api.Repository(
            client_eva,
            owner='scality',
            repo_slug=('%s_%s' % (self.args.repo_prefix,
                                  self.args.your_login)),
        )
        # Wall-E may want to comment manually too
        client_wall_e = bitbucket_api.Client(
            WALL_E_USERNAME,
            self.args.wall_e_password,
            WALL_E_EMAIL)
        self.bbrepo_wall_e = bitbucket_api.Repository(
            client_wall_e,
            owner='scality',
            repo_slug=('%s_%s' % (self.args.repo_prefix,
                                  self.args.your_login)),
        )
        self.gitrepo = GitRepository(self.bbrepo.get_git_url())
        initialize_git_repo(self.gitrepo,
                            self.args.your_login,
                            self.args.your_mail)

    def tearDown(self):
        self.bbrepo.delete()
        self.gitrepo.delete()

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=None,
            file_=True,
            backtrace=False):
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
        retcode = self.handle(pr['id'], backtrace=backtrace)
        self.assertEqual(retcode, InitMessage.code)
        return pr

    def handle(self,
               pull_request_id,
               options=[],
               reference_git_repo='',
               no_comment=False,
               interactive=False,
               backtrace=False):

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
        sys.argv.append('--quiet')
        sys.argv.append('--settings')
        sys.argv.append('ring')

        sys.argv.append('--slug')
        sys.argv.append(self.bbrepo['repo_slug'])
        sys.argv.append(str(pull_request_id))
        sys.argv.append(self.args.wall_e_password)
        return wall_e.main()

    def test_full_merge_manual(self):
        """Test the following conditions:

        - Author approval required,
        - can merge successfully by bypassing all checks,
        - cannot merge a second time.

        """
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        # check backtrace mode on the same error, and check same error happens
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        options=['bypass_jira_check'],
                        backtrace=True)
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        # check success mode
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        # check integration branches have been removed
        for version in ['4.3', '5.1', '6.0']:
            remote = 'w/%s/%s' % (version, 'bugfix/RING-0001')
            ret = self.gitrepo.remote_branch_exists(remote)
            self.assertFalse(ret)

        # check what happens when trying to do it again
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'],
                        backtrace=True)
        # test the return code of a silent exception is 0
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, 0)

    def test_incompatible_prefixes(self):
        pr = self.create_pr('feature/RING-00001', 'development/4.3')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, IncompatibleSourceBranchPrefix.code)

        pr = self.create_pr('project/RING-00002', 'development/4.3')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, IncompatibleSourceBranchPrefix.code)

        pr = self.create_pr('bugfix/RING-00003', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

        pr = self.create_pr('improvement/RING-00004', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

        pr = self.create_pr('project/RING-00005', 'development/6.0')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

        pr = self.create_pr('feature/RING-00006', 'development/6.0')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

        pr = self.create_pr('feature/RING-00007', 'stabilization/4.3.18')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, IncompatibleSourceBranchPrefix.code)

        pr = self.create_pr('bugfix/RING-00008', 'stabilization/4.3.18')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

        pr = self.create_pr('feature/RING-00009', 'stabilization/6.0.0')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, IncompatibleSourceBranchPrefix.code)

        pr = self.create_pr('bugfix/RING-00010', 'stabilization/6.0.0')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_not_my_job_cases(self):
        feature_branch = 'feature/RING-00002'
        from_branch = 'development/6.0'
        create_branch(self.gitrepo, feature_branch, from_branch=from_branch,
                      file_=True)
        pr = self.bbrepo_eva.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': feature_branch}},
            destination={'branch': {'name': 'release/6.0'}},
            close_source_branch=True,
            description=''
        )
        with self.assertRaises(NotMyJob):
            self.handle(pr['id'], backtrace=True)

        create_branch(self.gitrepo, 'feature/RING-00001',
                      from_branch='development/4.3', file_=True)
        for destination in ['feature/RING-12345',
                            'improvement/RING-12345',
                            'project/RING-12345',
                            'bugfix/RING-12345',
                            'user/my_own_branch',
                            'project/invalid',
                            'feature/invalid',
                            'hotfix/customer']:
            create_branch(self.gitrepo, destination,
                          from_branch='development/4.3', file_=True)
            pr = self.bbrepo_eva.create_pull_request(
                title='title',
                name='name',
                source={'branch': {'name': 'feature/RING-00001'}},
                destination={'branch': {'name': destination}},
                close_source_branch=True,
                description=''
            )
            with self.assertRaises(NotMyJob):
                self.handle(pr['id'], backtrace=True)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/5.1',
                             file_='toto.txt')
        pr2 = self.create_pr('improvement/RING-0006', 'development/5.1',
                             file_='toto.txt')
        pr3 = self.create_pr('improvement/RING-0006-other', 'development/4.3',
                             file_='toto.txt')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr1['id'], options=self.bypass_all)
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr2['id'], options=self.bypass_all)
        try:
            self.handle(pr2['id'],
                        options=self.bypass_all,
                        backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`improvement/RING-0006`\ninto integration branch "
                "`w/5.1/improvement/RING-0006`",
                e.msg)
            # Wall-E shouldn't instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertNotIn(
                "git checkout w/5.1/improvement/RING-0006",
                e.msg)
        else:
            self.fail("No conflict detected.")

        try:
            self.handle(pr3['id'],
                        options=self.bypass_all,
                        backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`w/4.3/improvement/RING-0006-other`\ninto integration branch "
                "`w/5.1/improvement/RING-0006-other`",
                e.msg)
            # Wall-E MUST instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn(
                "git checkout w/5.1/improvement/RING-0006",
                e.msg)
            self.assertIn(
                "git merge origin/w/4.3/improvement/RING-0006",
                e.msg)
            self.assertIn(
                "git push origin HEAD:w/5.1/improvement/RING-0006",
                e.msg)
        else:
            self.fail("No conflict detected.")

    def test_approvals(self):
        """Test approvals of author, reviewer and tester."""
        feature_branch = 'bugfix/RING-0007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # test approval on sub pr has not effect
        pr_child = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        pr_child.approve()
        retcode = self.handle(pr['id']+1, options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # Author adds approval
        pr.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # Reviewer adds approval
        pr_peer = self.bbrepo.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, TesterApprovalRequired.code)

        # Tester adds approval
        pr_tester = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_tester.approve()
        retcode = self.handle(pr['id'], options=[
                              'bypass_jira_check',
                              'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_branches_creation_main_pr_not_approved(self):
        """Test if Wall-e creates integration pull-requests when the main
        pull-request isn't approved.

        1. Create feature branch and create an unapproved pull request
        2. Run wall-e on the pull request
        3. Check existence of integration branches

        """
        for feature_branch in ['bugfix/RING-0008', 'bugfix/RING-0008-label']:
            dst_branch = 'stabilization/4.3.18'
            pr = self.create_pr(feature_branch, dst_branch)
            # bypass IntegrationPullRequestsCreated Exception
            self.handle(pr['id'], options=['bypass_jira_check'])
            retcode = self.handle(pr['id'], options=['bypass_jira_check'])
            self.assertEqual(retcode, AuthorApprovalRequired.code)

            # check existence of integration branches
            for version in ['4.3', '5.1', '6.0']:
                remote = 'w/%s/%s' % (version, feature_branch)
                ret = self.gitrepo.remote_branch_exists(remote)
                self.assertTrue(ret)
            remote = 'w/4.3.18/%s' % feature_branch
            ret = self.gitrepo.remote_branch_exists(remote)
            self.assertTrue(ret)

            # check absence of a missing branch
            self.assertFalse(self.gitrepo.remote_branch_exists(
                'missing_branch'))

    def test_from_unrecognized_source_branch(self):
        for source in ['master2',
                       'feaure/RING-12345']:
            create_branch(self.gitrepo, source,
                          from_branch='development/4.3', file_=True)
            pr = self.bbrepo_eva.create_pull_request(
                title='title',
                name='name',
                source={'branch': {'name': source}},
                destination={'branch': {'name': 'development/4.3'}},
                close_source_branch=True,
                description=''
            )
            with self.assertRaises(UnrecognizedBranchPattern):
                self.handle(pr['id'], backtrace=True)

    def test_inclusion_of_jira_issue(self):
        pr = self.create_pr('bugfix/00066', 'development/4.3')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

        pr = self.create_pr('improvement/i', 'development/4.3')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

        # merge to latest dev branch does not require a ticket
        pr = self.create_pr('bugfix/free_text', 'development/6.0')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'])
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        pr = self.create_pr('bugfix/free_text2', 'stabilization/6.0.0')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

    def test_to_unrecognized_destination_branch(self):
        create_branch(self.gitrepo, 'master2',
                      from_branch='development/4.3', file_=True)
        create_branch(self.gitrepo, 'bugfix/RING-00001',
                      from_branch='development/4.3', file_=True)
        pr = self.bbrepo_eva.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': 'bugfix/RING-00001'}},
            destination={'branch': {'name': 'master2'}},
            close_source_branch=True,
            description=''
        )
        with self.assertRaises(UnrecognizedBranchPattern):
            self.handle(pr['id'], backtrace=True)

    def test_main_pr_retrieval(self):
        # create integration PRs first:
        pr = self.create_pr('bugfix/RING-00066', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])
        retcode = self.handle(pr['id'],
                              options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        # simulate a child pr update
        retcode = self.handle(pr['id']+1,
                              options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

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

    def test_norepeat_strategy(self):
        def get_last_comment(pr):
            """Helper function to get the last comment of a pr.

            returns the md5 digest of the last comment for easier comparison.

            """
            return md5(
                list(pr.get_comments())[-1]['content']['raw']
            ).digest()

        pr = self.create_pr('bugfix/RING-01334', 'development/4.3',
                            file_='toto.txt')

        # The help message should be displayed every time the user requests it
        help_msg = ''
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        try:
            self.handle(pr['id'], backtrace=True)
        except HelpMessage as ret:
            help_msg = md5(ret.msg).digest()

        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, help_msg,
                         "Wall-e didn't post the first help message.")

        pr.add_comment("Ok, ok")
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, help_msg,
                            "Eva's message wasn't recorded.")

        pr.add_comment('@%s help' % WALL_E_USERNAME)
        self.handle(pr['id'])
        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, help_msg,
                         "Wall-E didn't post a second help message.")

        # Let's have Wall-E yield an actual AuthorApproval error message
        author_msg = ''
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])
        try:
            self.handle(pr['id'], options=['bypass_jira_check'],
                        backtrace=True)
        except AuthorApprovalRequired as ret:
            author_msg = md5(ret.msg).digest()

        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, author_msg,
                         "Wall-E didn't post his first error message.")

        pr.add_comment("OK, I Fixed it")
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, author_msg,
                            "Eva's message wasn't recorded.")

        # Wall-E should not repeat itself if the error is not fixed
        self.handle(pr['id'], options=['bypass_jira_check'])
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, author_msg,
                            "Wall-E repeated an error message when he "
                            "shouldn't have.")

        # Confront Wall-E to a different error (PeerApproval)
        self.handle(pr['id'],
                    options=['bypass_jira_check', 'bypass_author_approval'])

        # Re-produce the AuthorApproval error, Wall-E should re-send the
        # AuthorApproval message
        self.handle(pr['id'], options=['bypass_jira_check'])
        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, author_msg,
                         "Wall-E didn't respond to second occurrence of the "
                         "error.")

    def test_options_and_commands(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')

        # option: wait
        comment = pr.add_comment('@%s wait' % WALL_E_USERNAME)
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], backtrace=True)
        comment.delete()

        # command: build
        pr.add_comment('@%s build' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, CommandNotImplemented.code)

        # command: clear
        pr.add_comment('@%s clear' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, CommandNotImplemented.code)

        # command: status
        pr.add_comment('@%s status' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, StatusReport.code)

        # mix of option and command
        pr.add_comment('@%s unanimity' % WALL_E_USERNAME)
        pr.add_comment('@%s status' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, StatusReport.code)

        # test_help command
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, HelpMessage.code)

        # test help command with inter comment
        pr.add_comment('@%s: help' % WALL_E_USERNAME)
        pr.add_comment('an irrelevant comment')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, HelpMessage.code)

        # test help command with inter comment from wall-e
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        pr_wall_e = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_wall_e.add_comment('this is my help already')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # test unknown command
        comment = pr.add_comment('@%s helpp' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, UnknownCommand.code)
        comment.delete()

        # test command args
        pr.add_comment('@%s help some arguments --hehe' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, HelpMessage.code)

        # test incorrect address when setting options through comments
        pr.add_comment('@toto'  # toto is not Wall-E
                       ' bypass_author_approval'
                       ' bypass_peer_approval'
                       ' bypass_tester_approval'
                       ' bypass_build_status'
                       ' bypass_jira_check')
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # test options set through deleted comment(self):
        comment = pr.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_tester_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % WALL_E_USERNAME
        )
        comment.delete()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # test no effect sub pr options
        sub_pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        sub_pr_admin.add_comment('@%s'
                                 ' bypass_author_approval'
                                 ' bypass_peer_approval'
                                 ' bypass_build_status'
                                 ' bypass_jira_check' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

    def test_bypass_options(self):
        # test bypass all approvals through an incorrect bitbucket comment
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_aproval'  # a p is missing
            ' bypass_peer_approval'
            ' bypass_tester_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % WALL_E_USERNAME
        )
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, UnknownCommand.code)
        comment.delete()

        # test bypass all approvals through unauthorized bitbucket comment
        comment = pr.add_comment(
            '@%s'  # comment is made by unpriviledged Eva
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_tester_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % WALL_E_USERNAME
        )
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, NotEnoughCredentials.code)
        comment.delete()

        # test bypass all approvals through an unknown bitbucket comment
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_tester_approval'
            ' bypass_build_status'
            ' mmm_never_seen_that_before'  # this is unknown
            ' bypass_jira_check' % WALL_E_USERNAME
        )
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, UnknownCommand.code)
        comment.delete()

        # test approvals through a single bitbucket comment
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval'
                             ' bypass_build_status'
                             ' bypass_jira_check' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, IntegrationPullRequestsCreated.code)
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass all approvals through bitbucket comment extra spaces
        pr = self.create_pr('bugfix/RING-00002', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('  @%s  '
                             '   bypass_author_approval  '
                             '     bypass_peer_approval   '
                             ' bypass_tester_approval'
                             '  bypass_build_status'
                             '   bypass_jira_check' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'])
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass all approvals through many comments
        pr = self.create_pr('bugfix/RING-00003', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s bypass_author_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_peer_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_build_status' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_jira_check' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'])
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass all approvals through mix comments and cmdline
        pr = self.create_pr('bugfix/RING-00004', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_build_status',
                                       'bypass_jira_check'])
        retcode = self.handle(pr['id'], options=['bypass_build_status',
                                                 'bypass_jira_check'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass author approval through comment
        pr = self.create_pr('bugfix/RING-00005', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_author_approval']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_author_approval']))
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass peer approval through comment
        pr = self.create_pr('bugfix/RING-00006', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_peer_approval' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=['bypass_author_approval',
                             'bypass_tester_approval',
                             'bypass_jira_check',
                             'bypass_build_status'])
        retcode = self.handle(pr['id'],
                              options=['bypass_author_approval',
                                       'bypass_tester_approval',
                                       'bypass_jira_check',
                                       'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass jira check through comment
        pr = self.create_pr('bugfix/RING-00007', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_jira_check' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_author_approval',
                                       'bypass_tester_approval',
                                       'bypass_peer_approval',
                                       'bypass_build_status'])
        retcode = self.handle(pr['id'], options=['bypass_author_approval',
                                                 'bypass_tester_approval',
                                                 'bypass_peer_approval',
                                                 'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass build status through comment
        pr = self.create_pr('bugfix/RING-00009', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_build_status' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        self.assertEqual(retcode, SuccessMessage.code)

        # test options lost in many comments
        pr = self.create_pr('bugfix/RING-00010', 'development/4.3')
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
        pr_admin.add_comment('@%s bypass_jira_check' % WALL_E_USERNAME)
        for i in range(10):
            pr.add_comment('random comment %s' % i)
        for i in range(10):
            pr.add_comment('@%s bypass_tester_approval' % i)
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'])
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass all approvals through bitbucket comment extra chars
        pr = self.create_pr('bugfix/RING-00011', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s:'
                             'bypass_author_approval,  '
                             '     bypass_peer_approval,,   '
                             ' bypass_tester_approval'
                             '  bypass_build_status-bypass_jira_check' %
                             WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'])
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass branch prefix through comment
        pr = self.create_pr('feature/RING-00012', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_incompatible_branch' % WALL_E_USERNAME)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_rebased_feature_branch(self):
        pr = self.create_pr('bugfix/RING-00074', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            retcode = self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # create another PR and merge it entirely
        pr2 = self.create_pr('bugfix/RING-00075', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr2['id'], options=self.bypass_all)
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        rebase_branch(self.gitrepo, 'bugfix/RING-00075', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_first_integration_branch_manually_updated(self):
        feature_branch = 'bugfix/RING-0076'
        first_integration_branch = 'w/4.3/bugfix/RING-0076'
        pr = self.create_pr(feature_branch, 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')

        retcode = self.handle(pr['id'],
                              options=['bypass_jira_check'])
        self.assertEqual(retcode, BranchHistoryMismatch.code)

    def test_branches_not_self_contained(self):
        """Check that we can detect malformed git repositories."""
        feature_branch = 'bugfix/RING-0077'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        add_file_to_branch(self.gitrepo, 'development/4.3',
                           'file_pushed_without_wall-e.txt', do_push=True)

        with self.assertRaises(DevBranchesNotSelfContained):
            self.handle(pr['id'], options=self.bypass_all)

    def test_missing_development_branch(self):
        """Check that we can detect malformed git repositories."""
        feature_branch = 'bugfix/RING-0077'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        self.gitrepo.cmd('git push origin :development/6.0')

        with self.assertRaises(DevBranchDoesNotExist):
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

    def test_pr_skew_with_lagging_pull_request_data(self):
        if not TestWallE.args.disable_mock:
            self.skipTest('Not supported with mock bitbucket.'
                          ' Fix __getitem__("hash") if required')

        # create hook
        try:
            real = wall_e.WallE._create_pull_requests
            global local_child_prs
            local_child_prs = []

            def _create_pull_requests(*args, **kwargs):
                global local_child_prs
                child_prs = real(*args, **kwargs)
                local_child_prs = child_prs
                return child_prs

            wall_e.WallE._create_pull_requests = _create_pull_requests

            pr = self.create_pr('bugfix/RING-00081', 'development/6.0')
            # Create integration branch and child pr
            with self.assertRaises(BuildNotStarted):
                self.handle(pr['id'],
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

            # Set build status on child pr
            self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

            # Add a new commit
            self.gitrepo.cmd('git checkout bugfix/RING-00081')
            self.gitrepo.cmd('touch abc')
            self.gitrepo.cmd('git add abc')
            self.gitrepo.cmd('git commit -m "add new file"')
            self.gitrepo.cmd('git push origin')

            # now simulate a late bitbucket
            def _create_pull_requests2(*args, **kwargs):
                global local_child_prs
                return local_child_prs

            wall_e.WallE._create_pull_requests = _create_pull_requests2

            # Run Wall-E
            with self.assertRaises(BuildNotStarted):
                self.handle(pr['id'],
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

        finally:
            wall_e.WallE._create_pull_requests = real

    def test_pr_skew_with_new_external_commit(self):
        if not TestWallE.args.disable_mock:
            self.skipTest('Not supported with mock bitbucket.'
                          ' Fix __getitem__("hash") if required')

        pr = self.create_pr('bugfix/RING-00081', 'development/6.0')
        # Create integration branch and child pr
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # Set build status on child pr
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

        # create hook
        try:
            real = wall_e.WallE._create_pull_requests

            def _create_pull_requests(*args, **kwargs):
                # simulate the update of the integration PR (by addition
                # of a commit) by another process, (typically a user),
                # in between the start of Wall-E and his decision to merge
                self.gitrepo.cmd('git fetch')
                self.gitrepo.cmd('git checkout w/6.0/bugfix/RING-00081')
                self.gitrepo.cmd('touch abc')
                self.gitrepo.cmd('git add abc')
                self.gitrepo.cmd('git commit -m "add new file"')
                self.gitrepo.cmd('git push origin')
                sha1 = self.gitrepo.cmd(
                    'git rev-parse w/6.0/bugfix/RING-00081')

                child_prs = real(*args, **kwargs)
                # make 100% sure the PR is up-to-date (since BB lags):
                child_prs[0]['source']['commit']['hash'] = sha1
                return child_prs

            wall_e.WallE._create_pull_requests = _create_pull_requests

            # Run Wall-E
            with self.assertRaises(PullRequestSkewDetected):
                self.handle(pr['id'],
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

        finally:
            wall_e.WallE._create_pull_requests = real

    def test_build_key_on_main_pr_has_no_effect(self):
        pr = self.create_pr('bugfix/RING-00078', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        # create another PR, so that integration PR will have different
        # commits than source PR
        pr2 = self.create_pr('bugfix/RING-00079', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr2['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        # restart PR number 1 to update it with content of 2
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id'], 'FAILED')
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_build_status(self):
        pr = self.create_pr('bugfix/RING-00081', 'development/4.3')

        # test build not started
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test non related build key
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL', key='pipelin')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL', key='pipelin')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL', key='pipelin')
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test build status failed
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr['id']+3, 'FAILED')
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        self.assertEqual(retcode, BuildFailed.code)

        # test build status inprogress
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')
        with self.assertRaises(BuildInProgress):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test bypass tester approval through comment
        pr = self.create_pr('bugfix/RING-00078', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s bypass_tester_approval' % WALL_E_USERNAME)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=[
                        'bypass_author_approval',
                        'bypass_peer_approval',
                        'bypass_jira_check',
                        'bypass_build_status'])
        retcode = self.handle(pr['id'], options=[
                              'bypass_author_approval',
                              'bypass_peer_approval',
                              'bypass_jira_check',
                              'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_source_branch_history_changed(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        # see what happens when the source branch is deleted
        self.gitrepo.cmd('git checkout development/4.3')
        self.gitrepo.cmd('git push origin :bugfix/RING-00001')
        self.gitrepo.cmd('git branch -D bugfix/RING-00001')
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'],
                        options=self.bypass_all,
                        backtrace=True)
        # recreate branch with a different history
        create_branch(self.gitrepo, 'bugfix/RING-00001',
                      from_branch='development/4.3', file_="a_new_file")
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        self.assertEqual(retcode, BranchHistoryMismatch.code)

    def test_source_branch_commit_added(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        add_file_to_branch(self.gitrepo, 'bugfix/RING-00001',
                           'file_added_on_source_branch')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_source_branch_forced_pushed(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        create_branch(self.gitrepo, 'bugfix/RING-00002',
                      from_branch='development/4.3',
                      file_="another_new_file", do_push=False)
        self.gitrepo.cmd(
            'git push -u -f origin bugfix/RING-00002:bugfix/RING-00001')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all)
        self.assertEqual(retcode, BranchHistoryMismatch.code)

    def test_integration_branch_and_source_branch_updated(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)
        first_integration_branch = 'w/4.3/bugfix/RING-00001'
        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')
        add_file_to_branch(self.gitrepo, 'bugfix/RING-00001',
                           'file_added_on_source_branch')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all)
        self.assertEqual(retcode, BranchHistoryMismatch.code)

    def test_integration_branch_and_source_branch_force_updated(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all_but(['bypass_build_status']))
        with self.assertRaises(BuildNotStarted):
            self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)
        first_integration_branch = 'w/4.3/bugfix/RING-00001'
        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')
        create_branch(self.gitrepo, 'bugfix/RING-00002',
                      from_branch='development/4.3',
                      file_="another_new_file", do_push=False)
        self.gitrepo.cmd(
            'git push -u -f origin bugfix/RING-00002:bugfix/RING-00001')
        retcode = self.handle(pr['id'],
                              options=self.bypass_all)
        self.assertEqual(retcode, BranchHistoryMismatch.code)

    def successful_merge_into_stabilization_branch(self, branch_name,
                                                   expected_dest_branches):
        pr = self.create_pr('bugfix/RING-00001', branch_name)
        self.handle(pr['id'],
                    options=self.bypass_all)
        self.handle(pr['id'],
                    options=self.bypass_all)
        self.gitrepo.cmd('git pull -a')
        expected_result = set(expected_dest_branches)
        result = set(self.gitrepo
                     .cmd('git branch -r --contains origin/bugfix/RING-00001')
                     .replace(" ", "").split('\n')[:-1])
        self.assertEqual(expected_result, result)

    def test_successful_merge_into_stabilization_branch(self):
        self.successful_merge_into_stabilization_branch(
            'stabilization/4.3.18',
            ["origin/bugfix/RING-00001",
             "origin/development/4.3",
             "origin/development/5.1",
             "origin/development/6.0",
             "origin/stabilization/4.3.18"])

    def test_successful_merge_into_stabilization_branch_middle_cascade(self):
        self.successful_merge_into_stabilization_branch(
            'stabilization/5.1.4',
            ["origin/bugfix/RING-00001",
             "origin/development/5.1",
             "origin/development/6.0",
             "origin/stabilization/5.1.4"])

    def test_success_message_content(self):
        pr = self.create_pr('bugfix/RING-00001', 'stabilization/5.1.4')
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=[
            'bypass_build_status',
            'bypass_tester_approval',
            'bypass_peer_approval',
            'bypass_author_approval'])
        try:
            self.handle(pr['id'], options=[
                'bypass_build_status',
                'bypass_tester_approval',
                'bypass_peer_approval',
                'bypass_author_approval'],
                backtrace=True)
        except SuccessMessage as e:
            self.assertIn('* :heavy_check_mark: `stabilization/5.1.4`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/5.1`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/6.0`', e.msg)
            self.assertIn('* `stabilization/4.3.18`', e.msg)
            self.assertIn('* `stabilization/6.0.0`', e.msg)
            self.assertIn('* `development/4.3`', e.msg)

    def test_unanimity_option(self):
        """Test unanimity by passing option to wall_e"""
        feature_branch = 'bugfix/RING-0076'
        dst_branch = 'development/4.3'
        reviewers = [self.creator]

        pr = self.create_pr(feature_branch, dst_branch,
                            reviewers=reviewers)
        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'],
                    options=self.bypass_all + ['unanimity'])
        retcode = self.handle(pr['id'],
                              options=self.bypass_all + ['unanimity'])
        self.assertEqual(retcode, UnanimityApprovalRequired.code)

    def test_unanimity_required_all_approval(self, ):
        """Test unanimity with all approval required"""

        feature_branch = 'bugfix/RING-007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)

        pr.add_comment('@%s unanimity' % WALL_E_USERNAME)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr['id'], options=['bypass_jira_check'])

        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # Author adds approval
        pr.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # Reviewer adds approval
        pr_peer = self.bbrepo.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, TesterApprovalRequired.code)

        # Tester adds approval
        pr_tester = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_tester.approve()
        retcode = self.handle(pr['id'], options=[
                              'bypass_jira_check',
                              'bypass_build_status'])

    def test_after_pull_request(self):
        pr_opened = self.create_pr('bugfix/RING-00001', 'development/4.3')
        pr_declined = self.create_pr('bugfix/RING-00002', 'development/4.3')
        pr_declined.decline()
        blocked_pr = self.create_pr('bugfix/RING-00003', 'development/4.3')

        comment_declined = blocked_pr.add_comment(
            '@%s after_pull_request=%s' % (
                WALL_E_USERNAME, pr_declined['id']))

        retcode = self.handle(blocked_pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, AfterPullRequest.code)

        blocked_pr.add_comment('@%s unanimity after_pull_request=%s' % (
            WALL_E_USERNAME, pr_opened['id']))

        retcode = self.handle(blocked_pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, AfterPullRequest.code)

        comment_declined.delete()
        retcode = self.handle(blocked_pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, AfterPullRequest.code)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(pr_opened['id'], options=self.bypass_all)

        retcode = self.handle(pr_opened['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        # bypass IntegrationPullRequestsCreated Exception
        self.handle(blocked_pr['id'], options=self.bypass_all)
        retcode = self.handle(blocked_pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, UnanimityApprovalRequired.code)

    def test_bitbucket_lag_on_pr_status(self):
        """Bitbucket can be a bit long to update a merged PR's status.

        Check that Wall-E handles this case nicely and returns before creating
        integration PRs.

        """
        if not TestWallE.args.disable_mock:
            self.skipTest('Not supported with mock bitbucket.')

        try:
            real = wall_e.WallE._check_pr_state

            pr = self.create_pr('bugfix/RING-00081', 'development/6.0')
            # Skip IntegrationBranchesCreated
            self.handle(pr['id'], self.bypass_all)
            retcode = self.handle(pr['id'], self.bypass_all)
            self.assertEqual(retcode, SuccessMessage.code)

            wall_e.WallE._check_pr_state = lambda *args, **kwargs: None

            with self.assertRaises(NothingToDo):
                self.handle(pr['id'], self.bypass_all, backtrace=True)

        finally:
            self.bbrepo_wall_e.get_pull_request = real

    def test_pr_title_too_long(self):
        if not TestWallE.args.disable_mock:
            self.skipTest('Not supported with mock bitbucket.'
                          ' Fix __getitem__("hash") if required')

        create_branch(self.gitrepo, 'bugfix/RING-00001',
                      from_branch='development/4.3', file_=True)
        pr = self.bbrepo_eva.create_pull_request(
            title='A' * (bitbucket_api.MAX_PR_TITLE_LEN - 10),
            name='name',
            source={'branch': {'name': 'bugfix/RING-00001'}},
            destination={'branch': {'name': 'development/4.3'}},
            close_source_branch=True,
            description=''
        )
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, InitMessage.code)

        try:
            # skip IntegrationBranchCreated
            self.handle(pr['id'], options=self.bypass_all)
            retcode = self.handle(pr['id'], options=self.bypass_all)
        except requests.HTTPError as err:
            self.fail("Error from bitbucket: %s" % err.response.text)
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
    parser.add_argument('--disable-mock', action='store_true', default=False,
                        help='Disables the bitbucket mock (slower tests)')
    TestWallE.args = parser.parse_args()

    if TestWallE.args.your_login == WALL_E_USERNAME:
        print('Cannot use Wall-e as the tester, please use another login.')
        sys.exit(1)

    if TestWallE.args.your_login == EVA_USERNAME:
        print('Cannot use Eva as the tester, please use another login.')
        sys.exit(1)

    if TestWallE.args.your_login not in wall_e.SETTINGS['ring']['admins']:
        print('Cannot use %s as the tester, it does not belong to '
              'admins.' % TestWallE.args.your_login)
        sys.exit(1)

    if not TestWallE.args.disable_mock:
        bitbucket_api.Client = bitbucket_api_mock.Client
        bitbucket_api.Repository = bitbucket_api_mock.Repository
    jira_api.JiraIssue = jira_api_mock.JiraIssue

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
