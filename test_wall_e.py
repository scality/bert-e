#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import re
import sys
import time
import unittest
from collections import OrderedDict
from copy import deepcopy
from hashlib import md5

import bitbucket_api
import bitbucket_api_mock
import jira_api
import jira_api_mock
import requests
import wall_e
from git_api import Repository as GitRepository, Branch
from simplecmd import cmd, CommandError
from utils import RetryHandler
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
                               IncoherentQueues,
                               Merged,
                               MissingJiraId,
                               NotEnoughCredentials,
                               NothingToDo,
                               NotMyJob,
                               ParentPullRequestNotFound,
                               PeerApprovalRequired,
                               PullRequestDeclined,
                               PullRequestSkewDetected,
                               QueueConflict,
                               Queued,
                               QueuesNotValidated,
                               QueueOutOfOrder,
                               StatusReport,
                               SuccessMessage,
                               UnanimityApprovalRequired,
                               UnknownCommand,
                               UnrecognizedBranchPattern,
                               UnsupportedMultipleStabBranches,
                               UnsupportedTokenType,
                               VersionMismatch,
                               WallE_SilentException,
                               WallE_TemplateException)
from wall_e_exceptions import (MasterQueueDiverged,
                               MasterQueueLateVsDev,
                               MasterQueueLateVsInt,
                               MasterQueueMissing,
                               MasterQueueNotInSync,
                               MasterQueueYoungerThanInt,
                               QueueInclusionIssue,
                               QueueIncomplete,
                               QueueInconsistentPullRequestsOrder)

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
            repo.cmd('git tag %s.%s.%s', major, minor, micro-1)

    repo.cmd('git branch -d master')
    # the following command fail randomly on bitbucket, so retry
    repo.cmd("git push --all origin", retry=3)
    repo.cmd("git push --tags", retry=3)


def create_branch(repo, name, from_branch=None, file_=False, do_push=True):
    if from_branch:
        repo.cmd('git checkout %s', from_branch)
    repo.cmd('git checkout -b %s', name)
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

    def finalize_cascade(self, branches, tags, destination,
                         fixver, merge_paths=None):
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

        # check merge_paths now (finalize not required)
        if merge_paths:
            paths = c.get_merge_paths()
            self.assertEqual(len(merge_paths), len(paths))
            for exp_path, path in zip(merge_paths, paths):
                self.assertEqual(len(exp_path), len(path))
                for exp_branch, branch in zip(exp_path, path):
                    self.assertEqual(exp_branch, branch.name)

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
        merge_paths = [
            ['development/4.3', 'development/5.1', 'development/6.0'],
            ['stabilization/4.3.18', 'development/4.3',
             'development/5.1', 'development/6.0'],
            ['stabilization/5.1.4', 'development/5.1', 'development/6.0'],
        ]
        self.finalize_cascade(branches, tags, destination, fixver, merge_paths)

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
        merge_paths = [
            ['development/5.1', 'development/6.0']
        ]

        tags = []
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination,
                              fixver, merge_paths)

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
        merge_paths = [
            ['development/6.1'],
            ['stabilization/6.1.5', 'development/6.1']
        ]

        tags = []
        fixver = ['6.1.5']
        c = self.finalize_cascade(branches, tags, destination,
                                  fixver, merge_paths)
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

    def test_retry_handler(self):
        class DummyError(Exception):
            pass

        def dummy_func(num_fails, history, raise_exn=None):
            """Function that fails the `num_fails` first times it is called."""
            if raise_exn is not None:
                raise raise_exn
            history.append("attempt")
            if len(history) <= num_fails:
                raise DummyError

        # Retry for at most 5 seconds, with at most 2 seconds between attempts
        retry = RetryHandler(5, max_delay=2)

        with retry:
            history = []
            start = time.time()
            retry.run(dummy_func, 2, history, catch=DummyError)
            elapsed = time.time() - start

            self.assertGreaterEqual(elapsed, 3)
            self.assertLess(elapsed, 4)
            self.assertEqual(3, len(history))

        with retry:
            start = time.time()
            history = []
            with self.assertRaises(DummyError):
                retry.run(dummy_func, 10, history)
            elapsed = time.time() - start
            self.assertGreaterEqual(elapsed, retry.limit)
            self.assertEqual(4, len(history))

        with retry:
            # Check that unpredicted errors are not silently caught
            start = time.time()
            with self.assertRaises(RuntimeError):
                retry.run(dummy_func, 1, [], raise_exn=RuntimeError,
                          catch=DummyError)
            elapsed = time.time() - start
            self.assertLess(elapsed, 1)

    def test_cmd(self):
        with self.assertRaises(CommandError):
            cmd('exit 1')

        start = time.time()
        with self.assertRaises(CommandError):
            cmd('sleep 5', timeout=0.5)
        self.assertLess(time.time() - start, 5)
        self.assertEqual('plop\n', cmd('echo plop'))


class FakeGitRepo:
    def includes_commit(self, commit):
        return True

    def cmd(self, command):
        return True


class RepositoryTests(unittest.TestCase):
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
            if RepositoryTests.args.disable_mock:
                time.sleep(5)  # don't be too agressive on API
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
        if RepositoryTests.args.disable_mock:
            time.sleep(5)  # don't be too agressive on API
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
        return pr

    def handle_legacy(self, token, backtrace):
        """Allow the legacy tests (tests dating back before
        the queueing system) to continue working without modification.

        Basically run a first instance of Wall-E, and in
        case the result is Queued, merge the PR immediately
        with a second call to Wall-E

        """
        if not backtrace:
            sys.argv.append('--backtrace')
        argv_copy = list(sys.argv)
        sys.argv.append(str(token))
        sys.argv.append(self.args.wall_e_password)
        try:
            wall_e.main()
        except Queued as queued_excp:
            pass
        except WallE_SilentException as excp:
            if backtrace:
                raise
            else:
                return 0
        except WallE_TemplateException as excp:
            if backtrace:
                raise
            else:
                return excp.code
        # set build status on q/* and wall-e again
        self.gitrepo.cmd('git fetch --prune')
        try:
            int(token)
            # token is a PR id, use its tip to filter on content
            # (caution: not necessarily the id of the main pr)
            pr = self.bbrepo_wall_e.get_pull_request(pull_request_id=token)
            sha1 = pr['source']['commit']['hash']
        except ValueError:
            # token is a sha1, use it to filter on content
            sha1 = token
        command = 'git branch -r --contains %s --list origin/q/[0-9]*/*'
        for qint in self.gitrepo.cmd(command, sha1) \
                        .replace(" ", "") \
                        .replace("origin/", "") \
                        .split('\n')[:-1]:
            branch = wall_e.branch_factory(self.gitrepo, qint)
            branch.checkout()
            sha1 = branch.get_latest_commit()
            self.set_build_status(sha1, 'SUCCESSFUL')
        sys.argv = argv_copy
        token = sha1
        sys.argv.append(str(token))
        sys.argv.append(self.args.wall_e_password)
        try:
            wall_e.main()
        except Merged:
            if backtrace:
                raise SuccessMessage(
                    branches=queued_excp.branches,
                    ignored=queued_excp.ignored,
                    issue=queued_excp.issue,
                    author=queued_excp.author,
                    active_options=queued_excp.active_options)
            else:
                return SuccessMessage.code
        except Exception:
            raise

    def handle(self,
               token,
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
        if self.args.disable_queues:
            sys.argv.append('--disable-queues')
        else:
            if self.__class__ == TestWallE:
                return self.handle_legacy(token, backtrace)

        sys.argv.append(str(token))
        sys.argv.append(self.args.wall_e_password)
        return wall_e.main()

    def set_build_status(self, sha1, state,
                         key='pre-merge',
                         name='Test build status',
                         url='http://www.scality.com'):
        self.bbrepo_wall_e.set_build_status(
            revision=sha1,
            key=key,
            state=state,
            name=name,
            url=url
        )

    def get_build_status(self, sha1, key='pipeline'):
        try:
            status = self.bbrepo_wall_e.get_build_status(
                revision=sha1,
                key=key,
            )
        except requests.HTTPError:
            status = ''
        return status

    def set_build_status_on_pr_id(self, pr_id, state,
                                  key='pre-merge',
                                  name='Test build status',
                                  url='http://www.scality.com'):
        pr = self.bbrepo_wall_e.get_pull_request(pull_request_id=pr_id)

        self.set_build_status(pr['source']['commit']['hash'],
                              state, key, name, url)
        # workaround laggy bitbucket
        if TestWallE.args.disable_mock:
            for _ in range(20):
                time.sleep(5)
                if self.get_build_status_on_pr_id(pr_id, key=key) != state:
                    continue
                return
            self.fail('Laggy Bitbucket detected.')

    def get_build_status_on_pr_id(self, pr_id, key='pipeline'):
        pr = self.bbrepo_wall_e.get_pull_request(pull_request_id=pr_id)
        return self.get_build_status(pr['source']['commit']['hash'], key)


class TestWallE(RepositoryTests):
    def test_full_merge_manual(self):
        """Test the following conditions:

        - Author approval required,
        - can merge successfully by bypassing all checks,
        - cannot merge a second time.

        """
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
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

        assert pr['id'] in wall_e.STATUS.get('merged PRs', [])

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
        pr2 = self.create_pr('bugfix/RING-0006-other', 'development/5.1',
                             file_='toto.txt')
        pr3 = self.create_pr('improvement/RING-0006', 'development/5.1',
                             file_='toto.txt')
        pr4 = self.create_pr('improvement/RING-0006-other', 'development/4.3',
                             file_='toto.txt')
        # Start PR2 (create integration branches) first

        self.handle(
            pr2['id'], self.bypass_all_but(['bypass_author_approval'])
        )
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        # Pursue PR2 (conflict on branch development/5.1 vs. w/ branch)
        try:
            self.handle(pr2['id'], options=self.bypass_all, backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`w/5.1/bugfix/RING-0006-other` with\ncontents from "
                "`bugfix/RING-0006-other` and `development/5.1`",
                e.msg)
            # Wall-E shouldn't instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn('on **the feature branch** '
                          '(`bugfix/RING-0006-other`', e.msg)
            self.assertNotIn("git checkout w/5.1/bugfix/RING-0006-other",
                             e.msg)
        else:
            self.fail("No conflict detected.")

        try:
            self.handle(pr3['id'], options=self.bypass_all, backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`w/5.1/improvement/RING-0006` with\ncontents from "
                "`improvement/RING-0006` and `development/5.1`",
                e.msg)
            # Wall-E shouldn't instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn('on **the feature branch** (`improvement/RING-0006`',
                          e.msg)
            self.assertNotIn("git checkout w/5.1/improvement/RING-0006", e.msg)
        else:
            self.fail("No conflict detected.")

        try:
            self.handle(pr4['id'],
                        options=self.bypass_all,
                        backtrace=True)
        except Conflict as e:
            self.assertIn(
                "`w/5.1/improvement/RING-0006-other` with\ncontents from "
                "`w/4.3/improvement/RING-0006-other` and "
                "`development/5.1`",
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

        # 1st reviewer adds approval
        pr_peer1 = self.bbrepo.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer1.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # 2nd reviewer adds approval
        pr_peer2 = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer2.approve()
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

        pr = self.create_pr('bugfix/00067', 'development/6.0')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

        pr = self.create_pr('improvement/i', 'development/4.3')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

        pr = self.create_pr('bugfix/free_text', 'development/6.0')
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, MissingJiraId.code)

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
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
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
        try:
            self.handle(
                pr['id'], options=['bypass_jira_check'], backtrace=True)
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
        # test RELENG-1335: WallE unvalid status command

        feature_branch = 'bugfix/RING-007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)
        pr.add_comment('@%s status?' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'], options=[
            'bypass_jira_check',
            'bypass_author_approval',
            'bypass_tester_approval',
            'bypass_peer_approval'])
        self.assertEqual(retcode, UnknownCommand.code)

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
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass all approvals through mix comments and cmdline
        pr = self.create_pr('bugfix/RING-00004', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_tester_approval' % WALL_E_USERNAME)
        retcode = self.handle(pr['id'], options=['bypass_build_status',
                                                 'bypass_jira_check'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass author approval through comment
        pr = self.create_pr('bugfix/RING-00005', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval' % WALL_E_USERNAME)
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_author_approval']))
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass peer approval through comment
        pr = self.create_pr('bugfix/RING-00006', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_peer_approval' % WALL_E_USERNAME)
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
        retcode = self.handle(pr['id'])
        self.assertEqual(retcode, SuccessMessage.code)

        # test bypass branch prefix through comment
        pr = self.create_pr('feature/RING-00012', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_incompatible_branch' % WALL_E_USERNAME)
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_incompatible_branch']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_rebased_feature_branch(self):
        pr = self.create_pr('bugfix/RING-00074', 'development/4.3')
        with self.assertRaises(BuildNotStarted):
            retcode = self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # create another PR and merge it entirely
        pr2 = self.create_pr('bugfix/RING-00075', 'development/4.3')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        rebase_branch(self.gitrepo, 'bugfix/RING-00075', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_first_integration_branch_manually_updated(self):
        feature_branch = 'bugfix/RING-0076'
        first_integration_branch = 'w/4.3/bugfix/RING-0076'
        pr = self.create_pr(feature_branch, 'development/4.3')
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

    def test_pr_skew_with_lagging_pull_request_data(self):
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
                if TestWallE.args.disable_mock:
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
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        # create another PR, so that integration PR will have different
        # commits than source PR
        pr2 = self.create_pr('bugfix/RING-00079', 'development/4.3')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)
        # restart PR number 1 to update it with content of 2
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        self.set_build_status_on_pr_id(pr['id'], 'FAILED')
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')
        retcode = self.handle(
            pr['id'],
            options=self.bypass_all_but(['bypass_build_status']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_build_status(self):
        pr = self.create_pr('bugfix/RING-00081', 'development/4.3')

        # test build not started
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

        retcode = self.handle(pr['id'], options=[
                              'bypass_author_approval',
                              'bypass_peer_approval',
                              'bypass_jira_check',
                              'bypass_build_status'])
        self.assertEqual(retcode, SuccessMessage.code)

    def test_build_status_triggered_by_build_result(self):
        pr = self.create_pr('bugfix/RING-00081', 'development/5.1')
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        self.set_build_status_on_pr_id(pr['id'] + 1, 'FAILED')
        self.set_build_status_on_pr_id(pr['id'] + 2, 'SUCCESSFUL')

        childpr = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'] + 1)

        retcode = self.handle(childpr['source']['commit']['hash'],
                              options=self.bypass_all_but(
                                  ['bypass_build_status']))
        self.assertEqual(retcode, BuildFailed.code)

        self.set_build_status_on_pr_id(pr['id'] + 1, 'SUCCESSFUL')

        retcode = self.handle(childpr['source']['commit']['hash'],
                              options=self.bypass_all_but(
                                  ['bypass_build_status']))
        self.assertEqual(retcode, SuccessMessage.code)

    def test_source_branch_history_changed(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
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

    def test_source_branch_commit_added_and_target_updated(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        pr2 = self.create_pr('bugfix/RING-00002', 'development/4.3')
        with self.assertRaises(BuildNotStarted):
            self.handle(pr['id'],
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # Source branch is modified
        add_file_to_branch(self.gitrepo, 'bugfix/RING-00001', 'some_file')
        # Another PR is merged
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        retcode = self.handle(pr['id'],
                              options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_source_branch_commit_added(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
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
        self.gitrepo.cmd('git pull -a --prune')
        expected_result = set(expected_dest_branches)
        result = set(self.gitrepo
                     .cmd('git branch -r --contains origin/bugfix/RING-00001')
                     .replace(" ", "").split('\n')[:-1])
        self.assertEqual(expected_result, result)

    def test_successful_merge_into_stabilization_branch(self):
        dest = 'stabilization/4.3.18'
        res = ["origin/bugfix/RING-00001",
               "origin/development/4.3",
               "origin/development/5.1",
               "origin/development/6.0",
               "origin/stabilization/4.3.18"]
        if not self.args.disable_queues:
            res.extend([
                "origin/q/4.3.18",
                "origin/q/4.3",
                "origin/q/5.1",
                "origin/q/6.0",
            ])
        self.successful_merge_into_stabilization_branch(dest, res)

    def test_successful_merge_into_stabilization_branch_middle_cascade(self):
        dest = 'stabilization/5.1.4'
        res = ["origin/bugfix/RING-00001",
               "origin/development/5.1",
               "origin/development/6.0",
               "origin/stabilization/5.1.4"]
        if not self.args.disable_queues:
            res.extend([
                "origin/q/5.1.4",
                "origin/q/5.1",
                "origin/q/6.0",
            ])
        self.successful_merge_into_stabilization_branch(dest, res)

    def test_success_message_content(self):
        pr = self.create_pr('bugfix/RING-00001', 'stabilization/5.1.4')
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
        retcode = self.handle(pr['id'],
                              options=self.bypass_all + ['unanimity'])
        self.assertEqual(retcode, UnanimityApprovalRequired.code)

    def test_unanimity_required_all_approval(self):
        """Test unanimity with all approval required"""

        feature_branch = 'bugfix/RING-007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)

        pr.add_comment('@%s unanimity' % WALL_E_USERNAME)

        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, AuthorApprovalRequired.code)

        # Author adds approval
        pr.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # 1st reviewer adds approval
        pr_peer = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_peer.approve()
        retcode = self.handle(pr['id'], options=['bypass_jira_check'])
        self.assertEqual(retcode, PeerApprovalRequired.code)

        # 2nd reviewer adds approval
        pr_peer = self.bbrepo_wall_e.get_pull_request(
            pull_request_id=pr['id'])
        pr_peer.approve()
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

        retcode = self.handle(pr_opened['id'], options=self.bypass_all)
        self.assertEqual(retcode, SuccessMessage.code)

        retcode = self.handle(blocked_pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, UnanimityApprovalRequired.code)

    def test_bitbucket_lag_on_pr_status(self):
        """Bitbucket can be a bit long to update a merged PR's status.

        Check that Wall-E handles this case nicely and returns before creating
        integration PRs.

        """
        try:
            real = wall_e.WallE._check_pr_state

            pr = self.create_pr('bugfix/RING-00081', 'development/6.0')
            retcode = self.handle(pr['id'], self.bypass_all)
            self.assertEqual(retcode, SuccessMessage.code)

            wall_e.WallE._check_pr_state = lambda *args, **kwargs: None

            with self.assertRaises(NothingToDo):
                self.handle(pr['id'], self.bypass_all, backtrace=True)

        finally:
            self.bbrepo_wall_e.get_pull_request = real

    def test_pr_title_too_long(self):
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

        try:
            retcode = self.handle(pr['id'], options=self.bypass_all)
        except requests.HTTPError as err:
            self.fail("Error from bitbucket: %s" % err.response.text)
        self.assertEqual(retcode, SuccessMessage.code)

    def test_main_pr_declined(self):
        """Check integration data (PR+branches) is deleted when original
        PR is declined."""
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        with self.assertRaises(BuildNotStarted):
            self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # check integration data is there
        branches = self.gitrepo.cmd(
            'git ls-remote origin w/*/bugfix/RING-00001')
        assert len(branches)
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        assert pr_['state'] == 'OPEN'
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+2)
        assert pr_['state'] == 'OPEN'
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+3)
        assert pr_['state'] == 'OPEN'

        pr.decline()
        with self.assertRaises(PullRequestDeclined):
            self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # check integration data is gone
        branches = self.gitrepo.cmd(
            'git ls-remote origin w/*/bugfix/RING-00001')
        assert branches == ''
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        assert pr_['state'] == 'DECLINED'
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+2)
        assert pr_['state'] == 'DECLINED'
        pr_ = self.bbrepo.get_pull_request(pull_request_id=pr['id']+3)
        assert pr_['state'] == 'DECLINED'

        # check nothing bad happens if called again
        with self.assertRaises(NothingToDo):
            self.handle(
                pr['id'],
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

    def test_branch_name_escape(self):
        """Make sure git api support branch names with
        special chars and doesn't interpret them in bash.

        """
        unescaped = 'bugfix/dangerous-branch-name-${RING}'

        # Bypass git-api to create the branch (explicit escape of the bad char)
        branch_name = unescaped.replace('$', '\$')
        cmd('git checkout development/5.1', cwd=self.gitrepo.cmd_directory)
        cmd('git checkout -b %s' % branch_name, cwd=self.gitrepo.cmd_directory)

        # Check that the branch exists with its unescaped name and the git-api
        self.assertTrue(Branch(self.gitrepo, unescaped).exists())

    def test_input_tokens(self):
        with self.assertRaises(UnsupportedTokenType):
            self.handle('toto')

        with self.assertRaises(UnsupportedTokenType):
            self.handle('1a2b3c')  # short sha1

        with self.assertRaises(UnsupportedTokenType):
            self.handle('/development/4.3')


class TestQueueing(RepositoryTests):
    """Tests which validate all things related to the merge queue.

    Theses tests are skipped if --disable-queues is passed to the runner.

       http://xkcd.com/853/

    """
    def setUp(self):
        if self.args.disable_queues:
            self.skipTest("skipping queue-related tests, "
                          "remove --disable-queues to activate")
        super(TestQueueing, self).setUp()

    def queue_branch(self, name):
        return wall_e.QueueBranch(self.gitrepo, name)

    def qint_branch(self, name):
        return wall_e.QueueIntegrationBranch(self.gitrepo, name)

    def submit_problem(self, problem, build_key='pipeline'):
        """Create a repository with dev, int and q branches ready."""
        self.bbrepo.invalidate_build_status_cache()
        for pr in problem.keys():
            pr_ = self.create_pr(problem[pr]['src'], problem[pr]['dst'])

            # run wall-e until creation of q branches
            retcode = self.handle(pr_['id'], options=self.bypass_all)
            self.assertEqual(retcode, Queued.code)

            # set build status on q branches
            if problem[pr]['dst'] == 'development/4.3':
                branches = [
                    'q/{pr}/4.3/{name}',
                    'q/{pr}/5.1/{name}',
                    'q/{pr}/6.0/{name}'
                ]
            elif problem[pr]['dst'] == 'stabilization/5.1.4':
                branches = [
                    'q/{pr}/5.1.4/{name}',
                    'q/{pr}/5.1/{name}',
                    'q/{pr}/6.0/{name}'
                ]
            elif problem[pr]['dst'] == 'development/5.1':
                branches = [
                    'q/{pr}/5.1/{name}',
                    'q/{pr}/6.0/{name}'
                ]
            elif problem[pr]['dst'] == 'development/6.0':
                branches = [
                    'q/{pr}/6.0/{name}'
                ]
            else:
                raise Exception('invalid dst branch name')

            qbranches = [branch.format(pr=pr_['id'], name=problem[pr]['src'])
                         for branch in branches]

            self.gitrepo.cmd('git fetch')
            for status, qbranch in zip(problem[pr]['status'], qbranches):
                for build_key in status.keys():
                    branch = self.qint_branch(qbranch)
                    branch.checkout()
                    self.set_build_status(
                        sha1=branch.get_latest_commit(),
                        key=build_key,
                        state=status[build_key]
                    )

        # return all qbranches
        return self.get_qbranches()

    def get_qbranches(self):
        return (self.gitrepo
                    .cmd('git branch -r --list "origin/q/*"')
                    .replace(" ", "")
                    .replace("origin/", "")
                    .split('\n')[:-1])

    def get_qint_branches(self):
        return (self.gitrepo
                    .cmd('git branch -r --list "origin/q/[0-9]*/*"')
                    .replace(" ", "")
                    .replace("origin/", "")
                    .split('\n')[:-1])

    def feed_queue_collection(self, qbranches):
        qc = wall_e.QueueCollection(
            self.bbrepo_wall_e,
            'pipeline',
            merge_paths=[  # see initialize_git_repo
                [wall_e.branch_factory(FakeGitRepo(), 'development/4.3'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/5.1'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/6.0')],

                [wall_e.branch_factory(FakeGitRepo(), 'stabilization/4.3.18'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/4.3'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/5.1'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/6.0')],

                [wall_e.branch_factory(FakeGitRepo(), 'stabilization/5.1.4'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/5.1'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/6.0')],

                [wall_e.branch_factory(FakeGitRepo(), 'stabilization/6.0.0'),
                 wall_e.branch_factory(FakeGitRepo(), 'development/6.0')],
            ])
        for qbranch in qbranches:
            qc._add_branch(wall_e.branch_factory(self.gitrepo, qbranch))
        return qc

    def test_queue_branch(self):
        with self.assertRaises(BranchNameInvalid):
            self.queue_branch("q/4.3/feature/RELENG-001-plop")

        qbranch = wall_e.branch_factory(FakeGitRepo(), "q/5.1")
        self.assertEqual(type(qbranch), wall_e.QueueBranch)
        self.assertEqual(qbranch.version, "5.1")
        self.assertEqual(qbranch.major, 5)
        self.assertEqual(qbranch.minor, 1)

    def test_qint_branch(self):
        with self.assertRaises(BranchNameInvalid):
            self.qint_branch("q/6.3")

        with self.assertRaises(BranchNameInvalid):
            self.qint_branch("q/6.2/feature/RELENG-001-plop")

        qint_branch = wall_e.branch_factory(FakeGitRepo(),
                                            "q/10/6.2/feature/RELENG-001-plop")
        self.assertEqual(type(qint_branch), wall_e.QueueIntegrationBranch)
        self.assertEqual(qint_branch.version, "6.2")
        self.assertEqual(qint_branch.pr_id, 10)
        self.assertEqual(qint_branch.major, 6)
        self.assertEqual(qint_branch.minor, 2)
        self.assertEqual(qint_branch.jira_project, 'RELENG')

    def test_queueing_no_queues_in_repo(self):
        qc = self.feed_queue_collection({})
        qc.finalize()
        qc.validate()
        assert qc.mergeable_prs == []

    @property
    def standard_problem(self):
        """This is the standard problem to submit to submit_problem.

        This is a list of pull requests, listed in the order of their
        creation.

        """
        status = {'pipeline': 'SUCCESSFUL', 'other': 'FAILED'}
        return OrderedDict({
            1: {'dst': 'development/4.3', 'src': 'improvement/bar',
                'status': [status] * 3},
            2: {'dst': 'development/6.0', 'src': 'feature/foo',
                'status': [status]},
            3: {'dst': 'development/5.1', 'src': 'bugfix/bar',
                'status': [status] * 2},
            4: {'dst': 'development/4.3', 'src': 'improvement/bar2',
                'status': [status] * 3}
        })

    @property
    def empty_solution(self):
        """This is the solution when nothing can be merged."""
        return OrderedDict([
            ('4.3', {
                wall_e.QueueBranch: self.queue_branch('q/4.3'),
                wall_e.QueueIntegrationBranch: []
            }),
            ('5.1', {
                wall_e.QueueBranch: self.queue_branch('q/5.1'),
                wall_e.QueueIntegrationBranch: []
            }),
            ('6.0', {
                wall_e.QueueBranch: self.queue_branch('q/6.0'),
                wall_e.QueueIntegrationBranch: []
            }),
        ])

    @property
    def standard_solution(self):
        """This is the solution to the standard problem."""
        return OrderedDict([
            ('4.3', {
                wall_e.QueueBranch: self.queue_branch('q/4.3'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/4.3/improvement/bar2'),
                    self.qint_branch('q/1/4.3/improvement/bar')
                ]
            }),
            ('5.1', {
                wall_e.QueueBranch: self.queue_branch('q/5.1'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/5.1/improvement/bar2'),
                    self.qint_branch('q/7/5.1/bugfix/bar'),
                    self.qint_branch('q/1/5.1/improvement/bar')
                ]
            }),
            ('6.0', {
                wall_e.QueueBranch: self.queue_branch('q/6.0'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/6.0/improvement/bar2'),
                    self.qint_branch('q/7/6.0/bugfix/bar'),
                    self.qint_branch('q/5/6.0/feature/foo'),
                    self.qint_branch('q/1/6.0/improvement/bar')
                ]
            }),
        ])

    def test_queueing_standard_problem(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7, 10]
        assert qc.mergeable_queues == self.standard_solution

    def test_queueing_standard_problem_reverse(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(reversed(qbranches))
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7, 10]
        assert qc.mergeable_queues == self.standard_solution

    def test_queueing_last_pr_build_not_started(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][wall_e.QueueIntegrationBranch].pop(0)
        solution['5.1'][wall_e.QueueIntegrationBranch].pop(0)
        solution['6.0'][wall_e.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7]
        assert qc.mergeable_queues == solution

    def test_queueing_last_pr_build_failed(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'pipeline': 'FAILED'}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][wall_e.QueueIntegrationBranch].pop(0)
        solution['5.1'][wall_e.QueueIntegrationBranch].pop(0)
        solution['6.0'][wall_e.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7]
        assert qc.mergeable_queues == solution

    def test_queueing_last_pr_other_key(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'other': 'SUCCESSFUL'}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][wall_e.QueueIntegrationBranch].pop(0)
        solution['5.1'][wall_e.QueueIntegrationBranch].pop(0)
        solution['6.0'][wall_e.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7]
        assert qc.mergeable_queues == solution

    def test_queueing_fail_masked_by_success(self):
        problem = deepcopy(self.standard_problem)
        problem[1]['status'][0] = {'pipeline': 'FAILED'}
        problem[2]['status'][0] = {'pipeline': 'FAILED'}
        problem[3]['status'][1] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == [1, 5, 7, 10]
        assert qc.mergeable_queues == self.standard_solution

    def test_queueing_all_failed(self):
        problem = deepcopy(self.standard_problem)
        for pr in problem.keys():
            for index_, _ in enumerate(problem[pr]['status']):
                problem[pr]['status'][index_] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == []
        assert qc.mergeable_queues == self.empty_solution

    def test_queueing_all_inprogress(self):
        problem = deepcopy(self.standard_problem)
        for pr in problem.keys():
            for index_, _ in enumerate(problem[pr]['status']):
                problem[pr]['status'][index_] = {'pipeline': 'INPROGRESS'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == []
        assert qc.mergeable_queues == self.empty_solution

    def test_queueing_mixed_fails(self):
        problem = deepcopy(self.standard_problem)
        problem[1]['status'][0] = {'pipeline': 'FAILED'}
        problem[2]['status'][0] = {'pipeline': 'FAILED'}
        problem[4]['status'][2] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == self.standard_solution
        assert qc.mergeable_prs == []
        assert qc.mergeable_queues == self.empty_solution

    def test_queueing_oldest_branch_fails(self):
        status = {'pipeline': 'SUCCESSFUL', 'other': 'FAILED'}
        problem = OrderedDict({
            1: {'dst': 'development/4.3', 'src': 'improvement/bar',
                'status': [status] * 3},
            2: {'dst': 'development/6.0', 'src': 'feature/foo',
                'status': [status]},
            3: {'dst': 'development/5.1', 'src': 'bugfix/bar',
                'status': [status] * 2},
            4: {'dst': 'development/5.1', 'src': 'improvement/bar2',
                'status': [status] * 3}
        })
        problem[1]['status'][0] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()

        qc.validate()
        assert qc.mergeable_prs == []

    def test_queues_not_validated(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(QueuesNotValidated):
            qc.mergeable_prs == [1, 5, 7, 10]

    def assert_error_codes(self, excp, errors):
        msg = excp.exception.args[0]
        error_codes = set(re.findall('Q[0-9]*', msg))
        expected = set([error.code for error in errors])
        assert error_codes == expected

    def test_validation_with_missing_master_queue(self):
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/5.1')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueMissing])

    def test_validation_updated_dev(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'development/4.3',
                           'file_pushed_without_wall-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueLateVsDev,
                                       QueueInclusionIssue])

    def test_validation_no_integration_queues(self):
        self.submit_problem(self.standard_problem)
        branches = ['q/4.3', 'q/5.1', 'q/6.0']
        qc = self.feed_queue_collection(branches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueNotInSync])

    def test_validation_masterq_on_dev(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git reset --hard development/6.0')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueLateVsInt,
                                       QueueInclusionIssue])

    def test_validation_masterq_late(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git reset --hard HEAD~')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueLateVsInt,
                                       QueueInclusionIssue])

    def test_validation_masterq_younger(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'q/4.3',
                           'file_pushed_without_wall-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueYoungerThanInt])

    def test_validation_masterq_diverged(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/5.1')
        self.gitrepo.cmd('git reset --hard HEAD~')
        add_file_to_branch(self.gitrepo, 'q/5.1',
                           'file_pushed_without_wall-e.txt', do_push=False)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueDiverged,
                                       QueueInclusionIssue])

    def test_validation_vertical_inclusion(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'q/10/5.1/improvement/bar2',
                           'file_pushed_without_wall-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [MasterQueueLateVsInt,
                                       QueueInclusionIssue])

    def test_validation_with_missing_first_intq(self):
        self.skipTest("skipping until completeness check is implemented")
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/1/4.3/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [QueueIncomplete])

    def test_validation_with_missing_middle_intq(self):
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/1/5.1/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [QueueInconsistentPullRequestsOrder])

    def test_validation_with_stabilization_branch(self):
        status = {'pipeline': 'SUCCESSFUL', 'other': 'FAILED'}
        problem = OrderedDict({
            1: {'dst': 'development/5.1', 'src': 'bugfix/bar',
                'status': [status] * 2},
            2: {'dst': 'development/6.0', 'src': 'feature/foo',
                'status': [status]},
            3: {'dst': 'stabilization/5.1.4', 'src': 'bugfix/foo',
                'status': [status] * 3},
            4: {'dst': 'development/4.3', 'src': 'bugfix/last',
                'status': [status] * 3},
        })
        solution = OrderedDict([
            ('4.3', {
                wall_e.QueueBranch: self.queue_branch('q/4.3'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/4.3/bugfix/last')
                ]
            }),
            ('5.1', {
                wall_e.QueueBranch: self.queue_branch('q/5.1'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/5.1/bugfix/last'),
                    self.qint_branch('q/6/5.1/bugfix/foo'),
                    self.qint_branch('q/1/5.1/bugfix/bar')
                ]
            }),
            ('5.1.4', {
                wall_e.QueueBranch: self.queue_branch('q/5.1.4'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/6/5.1.4/bugfix/foo')
                ]
            }),
            ('6.0', {
                wall_e.QueueBranch: self.queue_branch('q/6.0'),
                wall_e.QueueIntegrationBranch: [
                    self.qint_branch('q/10/6.0/bugfix/last'),
                    self.qint_branch('q/6/6.0/bugfix/foo'),
                    self.qint_branch('q/4/6.0/feature/foo'),
                    self.qint_branch('q/1/6.0/bugfix/bar')
                ]
            }),
        ])
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        assert qc._queues == solution
        assert qc.mergeable_prs == [1, 4, 6, 10]
        assert qc.mergeable_queues == solution

    def test_system_nominal_case(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_all_but(
            ['bypass_build_status']))

        # add a commit to w/5.1 branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/5.1/bugfix/RING-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        self.gitrepo.cmd('git push origin')
        sha1_w_5_1 = self.gitrepo \
                         .cmd('git rev-parse w/5.1/bugfix/RING-00001') \
                         .rstrip()

        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        # get the new sha1 on w/6.0 (set_build_status_on_pr_id won't detect the
        # new commit in mocked mode)
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/RING-00001')
        self.gitrepo.cmd('git pull')
        sha1_w_6_0 = self.gitrepo \
                         .cmd('git rev-parse w/6.0/bugfix/RING-00001') \
                         .rstrip()

        # check expected branches exist
        self.gitrepo.cmd('git fetch --prune')
        expected_branches = [
            'q/1/4.3/bugfix/RING-00001',
            'q/1/5.1/bugfix/RING-00001',
            'q/1/6.0/bugfix/RING-00001',
            'w/4.3/bugfix/RING-00001',
            'w/5.1/bugfix/RING-00001',
            'w/6.0/bugfix/RING-00001'
        ]
        for branch in expected_branches:
            assert self.gitrepo.remote_branch_exists(branch)

        # set build status
        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_5_1, state='SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_6_0, state='FAILED')
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], options=self.bypass_all, backtrace=True)

        with self.assertRaises(NothingToDo):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)
        self.set_build_status(sha1=sha1_w_6_0, state='SUCCESSFUL')
        with self.assertRaises(Merged):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

        status = wall_e.STATUS.get('merge queue', OrderedDict())
        assert 1 in status
        assert len(status[1]) == 3
        versions = tuple(version for version, _ in status[1])
        assert versions == ('6.0', '5.1', '4.3')
        # check validity of repo and branches
        for branch in ['q/4.3', 'q/5.1', 'q/6.0']:
            assert self.gitrepo.remote_branch_exists(branch)
        for branch in expected_branches:
            assert not self.gitrepo.remote_branch_exists(branch)
        for dev in ['development/4.3', 'development/5.1', 'development/6.0']:
            branch = wall_e.branch_factory(self.gitrepo, dev)
            branch.checkout()
            self.gitrepo.cmd('git pull origin %s', dev)
            assert branch.includes_commit(pr['source']['commit']['hash'])
            if dev == 'development/4.3':
                assert not branch.includes_commit(sha1_w_5_1)
            else:
                assert branch.includes_commit(sha1_w_5_1)
                self.gitrepo.cmd('cat abc')

        last_comment = list(pr.get_comments())[-1]['content']['raw']
        assert 'I have successfully merged' in last_comment
        assert 1 in wall_e.STATUS.get('merged PRs', [])

    def test_system_missing_integration_queue_before_in_queue(self):
        pr1 = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr2 = self.create_pr('bugfix/RING-00002', 'development/4.3')

        self.gitrepo.cmd('git push origin :q/1/5.1/bugfix/RING-00001')

        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, QueueOutOfOrder.code)

        retcode = self.handle(pr2['source']['commit']['hash'],
                              options=self.bypass_all)
        self.assertEqual(retcode, QueueOutOfOrder.code)

        with self.assertRaises(IncoherentQueues) as excp:
            self.handle(pr1['source']['commit']['hash'],
                        options=self.bypass_all)
        self.assert_error_codes(excp, [
            MasterQueueNotInSync,
            QueueInconsistentPullRequestsOrder
        ])

    def test_reconstruction(self):
        pr1 = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr2 = self.create_pr('bugfix/RING-00002', 'development/4.3')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        with self.assertRaises(NothingToDo):
            self.handle(pr1['id'], options=self.bypass_all, backtrace=True)

        # delete all q branches
        self.gitrepo.cmd('git fetch')
        dev = wall_e.branch_factory(self.gitrepo, 'development/4.3')
        dev.checkout()
        for qbranch in self.get_qbranches():
            branch = wall_e.branch_factory(self.gitrepo, qbranch)
            branch.checkout()  # get locally
            dev.checkout()  # move away
            branch.remove(do_push=True)

        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

    def test_decline_queued_pull_request(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        pr.decline()

        with self.assertRaises(PullRequestDeclined):
            self.handle(pr['id'], options=self.bypass_all, backtrace=True)

        # and yet it will merge
        with self.assertRaises(Merged):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_lose_integration_branches_after_queued(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

        # delete integration branch
        self.gitrepo.cmd('git fetch')
        dev = wall_e.branch_factory(self.gitrepo, 'development/6.0')
        intb = wall_e.branch_factory(self.gitrepo, 'w/6.0/bugfix/RING-00001')
        intb.destination_branch = dev
        intb.checkout()
        intb.remove(do_push=True)

        # and yet it will merge
        with self.assertRaises(Merged):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

    def set_build_status_on_branch_tip(self, branch_name, status):
        self.gitrepo.cmd('git fetch')
        branch = wall_e.branch_factory(self.gitrepo, branch_name)
        branch.checkout()
        sha1 = branch.get_latest_commit()
        self.set_build_status(sha1, status)
        return sha1

    def test_delete_all_integration_queues_of_one_pull_request(self):
        self.skipTest("skipping until completeness check is implemented")
        pr1 = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr2 = self.create_pr('bugfix/RING-00002', 'development/6.0')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        # delete integration queues of pr1
        self.gitrepo.cmd('git fetch')
        dev = wall_e.branch_factory(self.gitrepo, 'development/6.0')
        intq1 = wall_e.branch_factory(self.gitrepo,
                                      'q/1/6.0/bugfix/RING-00001')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        sha1 = self.set_build_status_on_branch_tip(
                'q/3/6.0/bugfix/RING-00002', 'SUCCESSFUL')

        with self.assertRaises(IncoherentQueues):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)

        # check the content of pr1 is not merged
        dev.checkout()
        self.gitrepo.cmd('git pull origin development/6.0')
        assert not dev.includes_commit(pr1['source']['commit']['hash'])

    def test_delete_main_queues(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        # delete main queue branch
        self.gitrepo.cmd('git fetch')
        dev = wall_e.branch_factory(self.gitrepo, 'development/6.0')
        intq1 = wall_e.branch_factory(self.gitrepo, 'q/6.0')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        with self.assertRaises(IncoherentQueues):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_feature_branch_augmented_after_queued(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

        old_sha1 = pr['source']['commit']['hash']

        # Add a new commit
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout bugfix/RING-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        sha1 = Branch(self.gitrepo, 'bugfix/RING-00001').get_latest_commit()
        self.gitrepo.cmd('git push origin')

        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], options=self.bypass_all, backtrace=True)

        with self.assertRaises(Merged):
            self.handle(old_sha1,
                        options=self.bypass_all,
                        backtrace=True)

        last_comment = list(pr.get_comments())[-1]['content']['raw']
        assert 'Partial merge' in last_comment
        assert sha1 in last_comment

        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        # check additional commit still here
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/RING-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('cat abc')
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('cat abc')

    def test_feature_branch_rewritten_after_queued(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

        old_sha1 = pr['source']['commit']['hash']

        # rewrite history of feature branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout bugfix/RING-00001')
        self.gitrepo.cmd('git commit --amend -m "rewritten log"')
        self.gitrepo.cmd('git push -f origin')

        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], options=self.bypass_all, backtrace=True)

        with self.assertRaises(Merged):
            self.handle(old_sha1,
                        options=self.bypass_all,
                        backtrace=True)

        last_comment = list(pr.get_comments())[-1]['content']['raw']
        assert 'Partial merge' in last_comment

        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

    def test_integration_branch_augmented_after_queued(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/6.0')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')

        # Add a new commit
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/RING-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        sha1 = Branch(self.gitrepo,
                      'w/6.0/bugfix/RING-00001').get_latest_commit()
        self.gitrepo.cmd('git push origin')

        with self.assertRaises(NothingToDo):
            self.handle(pr['id'], options=self.bypass_all, backtrace=True)

        with self.assertRaises(Merged):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

        with self.assertRaises(NothingToDo):
            retcode = self.handle(pr['id'], options=self.bypass_all,
                                  backtrace=True)

        self.gitrepo.cmd('git fetch')
        # Check the additional commit was not merged
        self.assertFalse(
            Branch(self.gitrepo, 'development/6.0').includes_commit(sha1))

    def test_integration_branches_dont_follow_dev(self):
        pr1 = self.create_pr('bugfix/RING-00001', 'development/4.3')
        # create integration branches but don't queue yet
        retcode = self.handle(pr1['id'], options=self.bypass_all_but(
            ['bypass_build_status']))

        # get the sha1's of integration branches
        self.gitrepo.cmd('git fetch')
        sha1s = dict()
        for version in ['4.3', '5.1', '6.0']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/RING-00001', version)
            self.gitrepo.cmd('git pull')
            sha1s[version] = self.gitrepo \
                .cmd('git rev-parse w/%s/bugfix/RING-00001', version) \
                .rstrip()

        # merge some other work
        pr2 = self.create_pr('bugfix/RING-00002', 'development/5.1')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)
        self.set_build_status_on_pr_id(pr2['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr2['id']+2, 'SUCCESSFUL')
        with self.assertRaises(Merged):
            self.handle(pr2['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

        # rerun on pr1, hope w branches don't get updated
        retcode = self.handle(pr1['id'], options=self.bypass_all_but(
            ['bypass_build_status']))

        # verify
        self.gitrepo.cmd('git fetch')
        for version in ['4.3', '5.1', '6.0']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/RING-00001', version)
            self.gitrepo.cmd('git pull')
            self.assertEqual(
                sha1s[version],
                self.gitrepo
                    .cmd('git rev-parse w/%s/bugfix/RING-00001', version)
                    .rstrip())

    def test_new_dev_branch_appears(self):
        pr = self.create_pr('bugfix/RING-00001', 'stabilization/5.1.4')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')

        # introduce a new version, but not its queue branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/6.0')
        self.gitrepo.cmd('git checkout -b development/6.3')
        self.gitrepo.cmd('git push -u origin development/6.3')

        with self.assertRaises(IncoherentQueues):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_dev_branch_decommissioned(self):
        pr = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+3, 'SUCCESSFUL')

        # delete a middle dev branch
        self.gitrepo.cmd('git push origin :development/5.1')

        with self.assertRaises(IncoherentQueues):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

    def prs_in_queue(self):
        self.gitrepo.cmd('git fetch --prune')
        prs = []
        for qint in self.get_qint_branches():
            branch = self.qint_branch(qint)
            prs.append(branch.pr_id)
        return set(prs)

    def test_new_stab_branch_appears(self):
        # introduce a new version
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/6.0')
        self.gitrepo.cmd('git checkout -b development/5.2')
        self.gitrepo.cmd('git push -u origin development/5.2')

        pr = self.create_pr('bugfix/RING-00001', 'development/5.2')
        retcode = self.handle(pr['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        self.set_build_status_on_pr_id(pr['id']+1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr['id']+2, 'SUCCESSFUL')

        # introduce a new stab, but not its queue branches
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/6.0')
        self.gitrepo.cmd('git checkout -b stabilization/5.2.0')
        self.gitrepo.cmd('git push -u origin stabilization/5.2.0')

        pr2 = self.create_pr('bugfix/RING-00002', 'stabilization/5.2.0')
        retcode = self.handle(pr2['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        assert self.prs_in_queue() == set([1, 4])

        with self.assertRaises(Merged):
            self.handle(pr['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

        assert self.prs_in_queue() == set([4])

        self.set_build_status_on_branch_tip(
            'q/4/5.2.0/bugfix/RING-00002', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/4/5.2/bugfix/RING-00002', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/4/6.0/bugfix/RING-00002', 'SUCCESSFUL')

        with self.assertRaises(Merged):
            self.handle(pr2['source']['commit']['hash'],
                        options=self.bypass_all,
                        backtrace=True)

        assert self.prs_in_queue() == set([])

    def test_multi_branch_queues(self):
        pr1 = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr5 = self.create_pr('bugfix/RING-00002', 'stabilization/5.1.4')
        retcode = self.handle(pr5['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr9 = self.create_pr('bugfix/RING-00003', 'development/4.3')
        retcode = self.handle(pr9['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        assert self.prs_in_queue() == set([1, 5, 9])

        self.set_build_status_on_branch_tip(
            'q/1/4.3/bugfix/RING-00001', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/1/5.1/bugfix/RING-00001', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/1/6.0/bugfix/RING-00001', 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/5/5.1.4/bugfix/RING-00002', 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/5/5.1/bugfix/RING-00002', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/5/6.0/bugfix/RING-00002', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/9/4.3/bugfix/RING-00003', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/9/5.1/bugfix/RING-00003', 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/9/6.0/bugfix/RING-00003', 'SUCCESSFUL')
        with self.assertRaises(NothingToDo):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([1, 5, 9])

        self.set_build_status_on_branch_tip(
            'q/1/6.0/bugfix/RING-00001', 'SUCCESSFUL')
        with self.assertRaises(Merged):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([5, 9])

        pr13 = self.create_pr('bugfix/RING-00004', 'stabilization/5.1.4')
        retcode = self.handle(pr13['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)
        with self.assertRaises(NothingToDo):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([5, 9, 13])

        self.set_build_status_on_branch_tip(
            'q/13/5.1.4/bugfix/RING-00004', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/13/5.1/bugfix/RING-00004', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/13/6.0/bugfix/RING-00004', 'FAIL')
        with self.assertRaises(NothingToDo):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([5, 9, 13])

        pr17 = self.create_pr('bugfix/RING-00005', 'development/6.0')
        retcode = self.handle(pr17['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)
        assert self.prs_in_queue() == set([5, 9, 13, 17])

        self.set_build_status_on_branch_tip(
            'q/17/6.0/bugfix/RING-00005', 'SUCCESSFUL')

        with self.assertRaises(Merged):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([])

    def test_multi_branch_queues_2(self):
        pr1 = self.create_pr('bugfix/RING-00001', 'development/4.3')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr5 = self.create_pr('bugfix/RING-00002', 'development/6.0')
        retcode = self.handle(pr5['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        assert self.prs_in_queue() == set([1, 5])

        self.set_build_status_on_branch_tip(
            'q/1/4.3/bugfix/RING-00001', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/1/5.1/bugfix/RING-00001', 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/1/6.0/bugfix/RING-00001', 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/5/6.0/bugfix/RING-00002', 'FAILED')
        with self.assertRaises(Merged):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)
        assert self.prs_in_queue() == set([5])

    def test_queue_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/6.0',
                             file_='toto.txt')
        retcode = self.handle(pr1['id'], options=self.bypass_all)
        self.assertEqual(retcode, Queued.code)

        pr2 = self.create_pr('bugfix/RING-0006-other', 'development/6.0',
                             file_='toto.txt')
        with self.assertRaises(QueueConflict):
            self.handle(pr2['id'],
                        options=self.bypass_all,
                        backtrace=True)

    def test_nothing_to_do_unknown_sha1(self):
        sha1 = "f" * 40
        with self.assertRaises(NothingToDo):
            self.handle(sha1,
                        options=self.bypass_all,
                        backtrace=True)


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
    parser.add_argument('--disable-queues', action='store_true', default=False,
                        help='deactivate queue feature during tests')
    RepositoryTests.args = parser.parse_args()

    if RepositoryTests.args.your_login == WALL_E_USERNAME:
        print('Cannot use Wall-e as the tester, please use another login.')
        sys.exit(1)

    if RepositoryTests.args.your_login == EVA_USERNAME:
        print('Cannot use Eva as the tester, please use another login.')
        sys.exit(1)

    if (RepositoryTests.args.your_login not in
            wall_e.SETTINGS['ring']['admins']):
        print('Cannot use %s as the tester, it does not belong to '
              'admins.' % RepositoryTests.args.your_login)
        sys.exit(1)

    if not RepositoryTests.args.disable_mock:
        bitbucket_api.Client = bitbucket_api_mock.Client
        bitbucket_api.Repository = bitbucket_api_mock.Repository
    jira_api.JiraIssue = jira_api_mock.JiraIssue

    if RepositoryTests.args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        # it is expected that wall-e issues some warning
        # during the tests, only report critical stuff
        logging.basicConfig(level=logging.CRITICAL)

    sys.argv = [sys.argv[0]]
    sys.argv.extend(RepositoryTests.args.tests)
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    unittest.main(failfast=RepositoryTests.args.failfast, testLoader=loader)


if __name__ == '__main__':
    main()
