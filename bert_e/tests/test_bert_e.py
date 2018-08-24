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
import re
import sys
import time
import unittest
import warnings
from collections import OrderedDict
from copy import deepcopy
from hashlib import md5
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import quote_plus

import requests
import requests_mock

from bert_e import exceptions as exns
from bert_e.bert_e import main as bert_e_main
from bert_e.bert_e import BertE
from bert_e.git_host import bitbucket as bitbucket_api
from bert_e.git_host import mock as bitbucket_api_mock
from bert_e.git_host.base import BertESession
from bert_e.git_host.base import NoSuchRepository
from bert_e.git_host.factory import client_factory
from bert_e.job import handler, CommitJob, Job, PullRequestJob
from bert_e.lib import jira as jira_api
from bert_e.lib.git import Repository as GitRepository
from bert_e.lib.git import Branch, MergeFailedException
from bert_e.lib.retry import RetryHandler
from bert_e.lib.simplecmd import CommandError, cmd
from bert_e.settings import setup_settings
from bert_e.workflow import gitwaterflow as gwf
from bert_e.workflow.gitwaterflow import branches as gwfb
from bert_e.workflow.gitwaterflow import integration as gwfi
from bert_e.workflow.gitwaterflow import queueing as gwfq
from bert_e.workflow.gitwaterflow.jobs import (EvalPullRequestJob,
                                               RebuildQueuesJob)

from .mocks import jira as jira_api_mock


FLAKINESS_MESSAGE_TITLE = 'Temporary bitbucket failure'  # noqa


DEFAULT_SETTINGS = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
always_create_integration_pull_requests: True
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 2
prefixes:
  Story: feature
  Bug: bugfix
  Improvement: improvement
jira_account_url: dummy
jira_username: dummy
jira_keys:
  - TEST
admins:
  - {admin}
project_leaders:
  - {admin}
tasks:
  - do foo
  - do bar
""" # noqa


class FaultJob(Job):
    """Fault job which will raise an exception to test sentry logging."""


class FaultError(Exception):
    """Exception raised on purpose from a FaultJob."""


@handler(FaultJob)
def handle_fault_job(job: FaultJob):
    raise FaultError("This is an exception raised when a fault job has been "
                     "handled for tests purposes.")


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
        create_branch(repo, 'release/' + major_minor, do_push=False)
        create_branch(repo, 'stabilization/' + full_version,
                      'release/' + major_minor, file_=True, do_push=False)
        create_branch(repo, 'development/' + major_minor,
                      'stabilization/' + full_version, file_=True,
                      do_push=False)
        if major != 6:
            repo.cmd('git tag %s.%s.%s', major, minor, micro - 1)

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
        repo.cmd('git push --set-upstream origin ' + branch_name)


def rebase_branch(repo, branch_name, on_branch):
    repo.cmd('git checkout ' + branch_name)
    repo.cmd('git rebase ' + on_branch)
    repo.cmd('git push -f')


def fake_answer_internal(status_code, *args, **kwargs):
    fake_answer_internal.attempt += 1
    response = Mock()
    if fake_answer_internal.attempt == 1:
        response.status_code = status_code
    else:
        response.status_code = 200
    response.request.method = "GET"
    response.request.url = "http://localhost/"
    response.elapsed.microseconds = 0

    return response


def dynamic_filtering(request):
    return FLAKINESS_MESSAGE_TITLE not in (request.text or '')


class QuickTest(unittest.TestCase):
    """Tests which don't need to interact with an external web services"""

    def feature_branch(self, name):
        return gwfb.FeatureBranch(None, name)

    @patch('requests.Session.request')
    def test_no_retry_200_answer(self, fake_request):
        fake_answer_internal.attempt = 0

        def fake_answer(*args, **kwargs):
            return fake_answer_internal(200,
                                        *args, **kwargs)
        fake_request.side_effect = fake_answer

        session = BertESession()
        response = session.request('GET', "http://localhost/")

        self.assertEqual(response.status_code, 200)

    @patch('requests.Session.request')
    def test_retry_429_answer(self, fake_request):
        fake_answer_internal.attempt = 0

        def fake_answer(*args, **kwargs):
            return fake_answer_internal(429,
                                        *args, **kwargs)
        fake_request.side_effect = fake_answer

        session = BertESession()
        response = session.request('GET', "http://localhost/")

        self.assertEqual(response.status_code, 200)

    @patch('requests.Session.request')
    def test_retry_500_answer(self, fake_request):
        fake_answer_internal.attempt = 0

        def fake_answer(*args, **kwargs):
            return fake_answer_internal(500,
                                        *args, **kwargs)
        fake_request.side_effect = fake_answer

        session = BertESession()
        response = session.request('GET', "http://localhost/")

        self.assertEqual(response.status_code, 200)

    def test_feature_branch_names(self):
        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('user/4.3/TEST-0005')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('TEST-0001-my-fix')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('my-fix')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('origin/feature/TEST-0001')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('/feature/TEST-0001')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('toto/TEST-0005')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('release/4.3')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('feature')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('feature/')

        # valid names
        self.feature_branch('feature/TEST-0005')
        self.feature_branch('improvement/TEST-1234')
        self.feature_branch('bugfix/TEST-1234')

        src = self.feature_branch('project/TEST-0005')
        self.assertEqual(src.jira_issue_key, 'TEST-0005')
        self.assertEqual(src.jira_project, 'TEST')

        src = self.feature_branch('feature/PROJECT-05-some-text_here')
        self.assertEqual(src.jira_issue_key, 'PROJECT-05')
        self.assertEqual(src.jira_project, 'PROJECT')

        src = self.feature_branch('feature/some-text_here')
        self.assertIsNone(src.jira_issue_key)
        self.assertIsNone(src.jira_project)

    def test_destination_branch_names(self):

        with self.assertRaises(exns.BranchNameInvalid):
            gwfb.DevelopmentBranch(repo=None, name='feature-TEST-0005')

        # valid names
        gwfb.DevelopmentBranch(repo=None, name='development/4.3')
        gwfb.DevelopmentBranch(repo=None, name='development/5.1')
        gwfb.DevelopmentBranch(repo=None, name='development/6.0')

    def finalize_cascade(self, branches, tags, destination,
                         fixver, merge_paths=None):
        c = gwfb.BranchCascade()

        all_branches = [
            gwfb.branch_factory(FakeGitRepo(), branch['name'])
            for branch in branches.values()]
        expected_dest = [
            gwfb.branch_factory(FakeGitRepo(), branch['name'])
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

        c.finalize(gwfb.branch_factory(FakeGitRepo(), destination))

        self.assertEqual(c.dst_branches, expected_dest)
        self.assertEqual(c.ignored_branches, expected_ignored)
        self.assertEqual(c.target_versions, fixver)
        return c

    def test_branch_cascade_from_master(self):
        destination = 'master'
        branches = OrderedDict({
            1: {'name': 'master', 'ignore': True}
        })
        tags = []
        fixver = []
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_from_dev_with_master(self):
        destination = 'development/1.0'
        branches = OrderedDict({
            1: {'name': 'master', 'ignore': True},
            2: {'name': 'development/1.0', 'ignore': True}
        })
        tags = []
        fixver = []
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_first_stab(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/4.3', 'ignore': False},
            3: {'name': 'development/5.1', 'ignore': False},
            4: {'name': 'stabilization/5.1.4', 'ignore': True},
            5: {'name': 'development/6.0', 'ignore': False}
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
            2: {'name': 'development/4.3', 'ignore': True},
            3: {'name': 'stabilization/5.1.4', 'ignore': False},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_t', '5.1.3', '5.1.4_rc1', '6.0.0']
        fixver = ['5.1.4', '6.0.1']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_first_dev(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': False},
            3: {'name': 'stabilization/5.1.4', 'ignore': True},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['4.3.18_rc1', '5.1.3', '5.1.4_rc1', '4.3.16', '4.3.17']
        fixver = ['4.3.19', '5.1.5', '6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_middle_dev(self):
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            3: {'name': 'stabilization/5.1.4', 'ignore': True},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1']
        fixver = ['5.1.5', '6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_last_dev(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            3: {'name': 'stabilization/5.1.4', 'ignore': True},
            4: {'name': 'development/5.1', 'ignore': True},
            5: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1']
        fixver = ['6.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_incorrect_stab_name(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/6.0', 'ignore': True},
            2: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['6.0.0']
        fixver = ['6.0.1']
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_targetting_incorrect_stab_name(self):
        destination = 'stabilization/6.0'
        branches = OrderedDict({
            1: {'name': 'stabilization/6.0', 'ignore': False},
            2: {'name': 'development/6.0', 'ignore': False}
        })
        tags = ['6.0.0']
        fixver = ['6.0.1']
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_dangling_stab(self):
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/5.1', 'ignore': False}
        })
        tags = ['4.3.17', '5.1.3']
        fixver = ['5.1.4']
        with self.assertRaises(exns.DevBranchDoesNotExist):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_targetting_dangling_stab(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.18', 'ignore': False},
            2: {'name': 'development/5.1', 'ignore': False}
        })
        tags = ['4.3.17', '5.1.3']
        fixver = ['4.3.18', '5.1.4']
        with self.assertRaises(exns.DevBranchDoesNotExist):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_multi_stab_branches(self):
        destination = 'stabilization/4.3.18'
        branches = OrderedDict({
            1: {'name': 'stabilization/4.3.17', 'ignore': True},
            2: {'name': 'stabilization/4.3.18', 'ignore': False},
            3: {'name': 'development/4.3', 'ignore': False}
        })
        tags = []
        fixver = []
        with self.assertRaises(exns.UnsupportedMultipleStabBranches):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_invalid_dev_branch(self):
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17', 'ignore': False}
        })
        tags = []
        fixver = []
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_tags_without_stabilization(self):
        destination = 'development/6.0'
        branches = OrderedDict({
            1: {'name': 'development/5.1', 'ignore': True},
            2: {'name': 'development/6.0', 'ignore': False}
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
            1: {'name': 'stabilization/6.1.5', 'ignore': False},
            2: {'name': 'development/6.1', 'ignore': False}
        })
        merge_paths = [
            ['development/6.1'],
            ['stabilization/6.1.5', 'development/6.1']
        ]

        tags = []
        fixver = ['6.1.5']
        c = self.finalize_cascade(branches, tags, destination,
                                  fixver, merge_paths)
        with self.assertRaises(exns.VersionMismatch):
            c.validate()

        tags = ['6.1.4']
        fixver = ['6.1.5']
        c = self.finalize_cascade(branches, tags, destination, fixver)
        self.assertEqual(
            c._cascade[(6, 1)][gwfb.DevelopmentBranch].micro, 6)
        self.assertEqual(
            c._cascade[(6, 1)][gwfb.StabilizationBranch].micro, 5)

        tags = ['6.1.5']
        fixver = []
        with self.assertRaises(exns.DeprecatedStabilizationBranch):
            self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['6.1.6']
        fixver = []
        with self.assertRaises(exns.DeprecatedStabilizationBranch):
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


class BuildFailedTest(unittest.TestCase):

    def test_build_fail_with_build_url(self):
        build_url = 'http://host/path/to/the?build=url'
        commit_url = 'http://host/path/to/the?commit=url'
        build_fail = exns.BuildFailed(branch='spam', build_url=build_url,
                                      commit_url=commit_url,
                                      active_options=None)
        self.assertIn('The [build]({}) for [commit]({})'
                      ' did not succeed'.format(build_url, commit_url),
                      build_fail.msg)

    def test_build_fail_with_url_to_none(self):
        build_fail = exns.BuildFailed(branch='spam', build_url=None,
                                      commit_url=None, active_options=None)
        self.assertIn('The build did not succeed', build_fail.msg)


class RepositoryTests(unittest.TestCase):
    bypass_all = [
        'bypass_author_approval',
        'bypass_build_status',
        'bypass_incompatible_branch',
        'bypass_jira_check',
        'bypass_peer_approval',
        'bypass_leader_approval'
    ]

    def get_last_pr_comment(self, pr):
        return list(pr.get_comments())[-1].text

    def bypass_all_but(self, exceptions):
        self.assertIsInstance(exceptions, list)
        bypasses = list(self.bypass_all)
        for exception in exceptions:
            bypasses.remove(exception)
        return bypasses

    def setUp(self):
        warnings.resetwarnings()
        warnings.simplefilter('ignore')
        # repo creator and reviewer
        self.creator = self.args.admin_username
        host = RepositoryTests.args.git_host
        client = client_factory(host, self.args.admin_username,
                                self.args.admin_password, "nobody@nowhere.com")
        try:
            client.delete_repository(
                owner=self.args.owner,
                slug=('%s_%s' % (self.args.repo_prefix,
                                 self.args.admin_username)),
            )
        except NoSuchRepository:
            pass

        self.admin_bb = client.create_repository(
            owner=self.args.owner,
            slug=('%s_%s' % (self.args.repo_prefix, self.args.admin_username))
        )

        # unprivileged user connection
        client = client_factory(
            host,
            self.args.contributor_username,
            self.args.contributor_password,
            "nobody@nowhere.com"
        )
        self.contributor_bb = client.get_repository(
            owner=self.args.owner,
            slug=('%s_%s' % (self.args.repo_prefix,
                             self.args.admin_username)),
        )
        # Bert-E may want to comment manually too
        client = client_factory(
            host,
            self.args.robot_username,
            self.args.robot_password,
            "nobody@nowhere.com")
        self.robot_bb = client.get_repository(
            owner=self.args.owner,
            slug=('%s_%s' % (self.args.repo_prefix,
                             self.args.admin_username)),
        )
        self.gitrepo = GitRepository(
            self.admin_bb.git_url,
            mask_pwd=quote_plus(self.args.admin_password)
        )
        initialize_git_repo(self.gitrepo,
                            self.args.admin_username,
                            "bert-e@scality.com")

    def tearDown(self):
        if RepositoryTests.args.git_host != 'mock':
            time.sleep(3)  # don't be too agressive on API
            self.admin_bb.client.delete_repository(owner=self.admin_bb.owner,
                                                   slug=self.admin_bb.slug)
        else:
            self.admin_bb.delete()

        self.gitrepo.delete()

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=None,
            file_=True,
            backtrace=False,
            reuse_branch=False):
        if reviewers is None:
            reviewers = [self.creator]
        if not reuse_branch:
            create_branch(self.gitrepo, feature_branch,
                          from_branch=from_branch, file_=file_)
        pr = self.contributor_bb.create_pull_request(
            title='title',
            name='name',
            src_branch=feature_branch,
            dst_branch=from_branch,
            close_source_branch=True,
            reviewers=[{'username': rev} for rev in reviewers],
            description=''
        )
        return pr

    def handle_legacy(self, token, backtrace):
        """Allow the legacy tests (tests dating back before
        the queueing system) to continue working without modification.

        Basically run a first instance of Bert-E, and in
        case the result is Queued, merge the PR immediately
        with a second call to Bert-E

        """
        queued_excp = None
        if not backtrace:
            sys.argv.append('--backtrace')
        argv_copy = list(sys.argv)
        sys.argv.append('test_settings.yml')
        sys.argv.append(self.args.robot_password)
        sys.argv.append('dummy_jira_password')
        sys.argv.append(str(token))
        try:
            bert_e_main()
        except exns.Queued as excp:
            queued_excp = excp
        except exns.SilentException as excp:
            if backtrace:
                raise
            else:
                return 0
        except exns.TemplateException as excp:
            if backtrace:
                raise
            else:
                return excp.code
        # set build status on q/* and Bert-E again
        self.gitrepo.cmd('git fetch --prune')
        try:
            int(token)
            # token is a PR id, use its tip to filter on content
            pr = self.robot_bb.get_pull_request(pull_request_id=token)
            if pr.author == self.args.robot_username:
                # Get main PR
                id = int(re.findall('\d+', pr.description)[0])
                pr = self.robot_bb.get_pull_request(pull_request_id=id)
            sha1 = pr.src_commit

        except ValueError:
            # token is a sha1, use it to filter on content
            sha1 = token
        command = 'git branch -r --contains %s --list origin/q/[0-9]*/*'
        for qint in self.gitrepo.cmd(command, sha1) \
                        .replace(" ", "") \
                        .replace("origin/", "") \
                        .split('\n')[:-1]:
            branch = gwfb.branch_factory(self.gitrepo, qint)
            branch.checkout()
            sha1 = branch.get_latest_commit()
            self.set_build_status(sha1, 'SUCCESSFUL')
        sys.argv = argv_copy
        token = sha1
        sys.argv.append('test_settings.yml')
        sys.argv.append(self.args.robot_password)
        sys.argv.append('dummy_jira_password')
        sys.argv.append(str(token))
        try:
            bert_e_main()
        except exns.Merged:
            if backtrace:
                raise exns.SuccessMessage(
                    branches=queued_excp.branches,
                    ignored=queued_excp.ignored,
                    issue=queued_excp.issue,
                    author=queued_excp.author,
                    active_options=queued_excp.active_options)
            else:
                return exns.SuccessMessage.code
        except Exception:
            raise

    def handle(self,
               token,
               options=[],
               no_comment=False,
               interactive=False,
               backtrace=False,
               settings=DEFAULT_SETTINGS):
        sys.argv = ["bert_e.py"]
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
        data = settings.format(
            admin=self.args.admin_username,
            contributor=self.args.contributor_username,
            robot=self.args.robot_username,
            owner=self.args.owner,
            slug='%s_%s' % (self.args.repo_prefix, self.args.admin_username),
            host=self.args.git_host
        )
        with open('test_settings.yml', 'w') as settings_file:
            settings_file.write(data)
        if self.args.disable_queues:
            sys.argv.append('--disable-queues')
        else:
            if self.__class__ == TestBertE:
                return self.handle_legacy(token, backtrace)

        sys.argv.append('test_settings.yml')
        sys.argv.append(self.args.robot_password)
        sys.argv.append('dummy_jira_password')
        sys.argv.append(str(token))
        return bert_e_main()

    def set_build_status(self, sha1, state, key='pre-merge',
                         name='Test build status',
                         url='https://www.test.com/build'):
        self.robot_bb.set_build_status(
            revision=sha1, key=key, state=state, url=url
        )

    def get_build_status(self, sha1, key='pipeline'):
        try:
            status = self.robot_bb.get_build_status(
                revision=sha1,
                key=key,
            )
        except requests.HTTPError:
            status = ''
        return status

    def set_build_status_on_pr_id(self, pr_id, state,
                                  key='pre-merge',
                                  name='Test build status',
                                  url='https://www.testurl.com/build/1'):
        pr = self.robot_bb.get_pull_request(pull_request_id=pr_id)

        self.set_build_status(pr.src_commit, state, key, name, url)
        # workaround laggy bitbucket
        if TestBertE.args.git_host != 'mock':
            for _ in range(20):
                time.sleep(5)
                if self.get_build_status_on_pr_id(pr_id, key=key) != state:
                    continue
                return
            self.fail('Laggy Bitbucket detected.')

    def get_build_status_on_pr_id(self, pr_id, key='pipeline'):
        pr = self.robot_bb.get_pull_request(pull_request_id=pr_id)
        return self.get_build_status(pr.src_commit, key)


class TestBertE(RepositoryTests):
    def test_full_merge_manual(self):
        """Test the following conditions:

        - Author approval required,
        - can merge successfully by bypassing all checks,
        - cannot merge a second time.

        """
        pr = self.create_pr('bugfix/TEST-0001', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # check backtrace mode on the same error, and check same error happens
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # check success mode
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # check integration branches have been removed
        for version in ['5.1', '6.0']:
            remote = 'w/%s/%s' % (version, 'bugfix/TEST-0001')
            self.assertFalse(self.gitrepo.remote_branch_exists(remote, True),
                             'branch %s shouldn\'t exist' % remote)

        # check feature branch still exists (the robot should not delete it)
        self.assertTrue(
            self.gitrepo.remote_branch_exists('bugfix/TEST-0001', True)
        )

        # check what happens when trying to do it again
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, backtrace=True)
        # test the return code of a silent exception is 0
        self.assertEqual(self.handle(pr.id), 0)

    def test_create_integration_pr_manually(self):
        """Test the create_pull_requests option."""
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_pull_requests: False
admins:
  - {admin}
""" # noqa
        pr = self.create_pr('feature/TEST-0002', 'development/4.3')
        options = ['create_pull_requests', 'bypass_jira_check']
        try:
            self.handle(pr.id)
        except requests.HTTPError as err:
            self.fail("Error: %s" % err.response.text)

        # Ensure that no integration PRs have been created
        with self.assertRaises(Exception):
            self.admin_bb.get_pull_request(pull_request_id=pr.id + 1)
        # Ask the robot to create all integration PR and ensure it's created
        self.handle(pr.id, settings=settings, options=options)
        # Ensure that all PRs have been created
        self.admin_bb.get_pull_request(pull_request_id=pr.id + 1)
        self.admin_bb.get_pull_request(pull_request_id=pr.id + 2)
        # Only two integration PRs should have been created
        with self.assertRaises(Exception):
            self.admin_bb.get_pull_request(pull_request_id=pr.id + 3)

    def test_comments_without_integration_pull_requests(self):
        """Test Bert-E PR comments on the latest development branch.

        1. Create a PR on the latest development branch,
        2. Ensure that no comments regarding integration branch has
           been created.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_pull_requests: False
admins:
  - {admin}
""" # noqa
        options = self.bypass_all_but(['bypass_build_status'])
        pr = self.create_pr('feature/TEST-0042', 'development/6.0')
        self.handle(pr.id, settings=settings, options=options)
        self.assertIs(len(list(pr.get_comments())), 1)
        self.assertIn('Hello %s' % self.args.contributor_username,
                      self.get_last_pr_comment(pr))

    def test_comments_for_manual_integration_pr_creation(self):
        """Test comments when integration data is created.

        1. Create a PR and ensure the proper message is sent regarding
           creation of the integration data,
        2. Request the creation of integration PRs and ensure the message
           is sent again,
        3. Ensure that no other comment has been created.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_pull_requests: False
admins:
  - {admin}
""" # noqa
        options = self.bypass_all_but(['bypass_build_status'])
        pr = self.create_pr('feature/TEST-0069', 'development/4.3')
        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 2)
        self.assertIn('Integration data created', self.get_last_pr_comment(pr))
        self.assertIn('You can set option', self.get_last_pr_comment(pr))
        self.assertNotIn('if you would like to be',
                         self.get_last_pr_comment(pr))

        pr.add_comment('Ok ok')
        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 3)

        comment = pr.add_comment('@%s create_pull_requests' %
                                 self.args.robot_username)
        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 5)
        self.assertIn('Integration data created', self.get_last_pr_comment(pr))
        self.assertNotIn('You can set option', self.get_last_pr_comment(pr))
        self.assertIn('if you would like to be', self.get_last_pr_comment(pr))

        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 5)

        comment.delete()
        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 4)

    def test_merge_without_integration_prs(self):
        """Test a normal Bert-E workflow with no integration PR.

        1. Ensure that no integration PRs have been created,
        2. Integration branches have been created properly,
        3. Ensure that Bert-E waits until all builds are successful,
        4. Ensure that Bert-E perform the merge,
        5. Ensure that the data is on all development branches.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_pull_requests: False
admins:
  - {admin}
""" # noqa
        src_branch = 'feature/TEST-0042'
        dst_branch = 'development/4.3'
        options = ['bypass_jira_check', 'bypass_peer_approval']

        pr = self.create_pr(src_branch, dst_branch)
        try:
            self.handle(pr.id, settings=settings, options=options)
        except requests.HTTPError as err:
            self.fail("Error: %s" % err.response.text)

        # Assert that no integration PRs haves been created
        with self.assertRaises(Exception):
            self.handle(pr.id + 1, settings=settings, options=options)
        self.gitrepo.cmd('git fetch --all')
        sha1_w_5_1 = self.gitrepo \
                         .cmd('git rev-parse origin/w/5.1/%s' % src_branch) \
                         .rstrip()
        sha1_w_6_0 = self.gitrepo \
                         .cmd('git rev-parse origin/w/6.0/%s' % src_branch) \
                         .rstrip()

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_5_1, state='SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_6_0, state='INPROGRESS')
        pr.approve()
        with self.assertRaises(exns.BuildInProgress):
            self.handle(pr.id, settings=settings,
                        options=options, backtrace=True)
        self.set_build_status(sha1=sha1_w_6_0, state='SUCCESSFUL')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(sha1_w_6_0, settings=settings,
                        options=options, backtrace=True)

        for dev in ['development/4.3', 'development/5.1', 'development/6.0']:
            branch = gwfb.branch_factory(self.gitrepo, dev)
            branch.checkout()
            self.gitrepo.cmd('git pull origin %s', dev)
            self.assertTrue(branch.includes_commit(pr.src_commit))

    def test_not_my_job_cases(self):
        feature_branch = 'feature/TEST-00002'
        from_branch = 'development/6.0'
        create_branch(self.gitrepo, feature_branch, from_branch=from_branch,
                      file_=True)
        pr = self.contributor_bb.create_pull_request(
            title='title', name='name', src_branch=feature_branch,
            dst_branch='release/6.0', close_source_branch=True, description=''
        )
        with self.assertRaises(exns.NotMyJob):
            self.handle(pr.id, backtrace=True)

        create_branch(self.gitrepo, 'feature/TEST-00001',
                      from_branch='development/4.3', file_=True)
        for destination in ['feature/TEST-12345',
                            'improvement/TEST-12345',
                            'project/TEST-12345',
                            'bugfix/TEST-12345',
                            'user/my_own_branch',
                            'project/invalid',
                            'feature/invalid',
                            'hotfix/customer']:
            create_branch(self.gitrepo, destination, file_=True,
                          from_branch='development/4.3')
            pr = self.contributor_bb.create_pull_request(
                title='title',
                name='name',
                src_branch='feature/TEST-00001',
                dst_branch=destination,
                close_source_branch=True,
                description=''
            )
            with self.assertRaises(exns.NotMyJob):
                self.handle(pr.id, backtrace=True)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/TEST-0006', 'development/6.0',
                             file_='toto.txt')
        pr2 = self.create_pr('bugfix/TEST-0006-other', 'development/6.0',
                             file_='toto.txt')
        pr3 = self.create_pr('improvement/TEST-0006', 'development/6.0',
                             file_='toto.txt')
        pr4 = self.create_pr('improvement/TEST-0006-other', 'development/5.1',
                             file_='toto.txt')
        pr5 = self.create_pr('improvement/TEST-0006-last', 'development/4.3',
                             file_='toto.txt')

        # Start PR2 (create integration branches) first
        self.handle(pr2.id, self.bypass_all_but(['bypass_author_approval']))
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        # Pursue PR2 (conflict on branch development/6.0 vs. feature branch)
        try:
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                'between your branch `bugfix/TEST-0006-other` and the\n'
                'destination branch `development/6.0`.',
                e.msg)
            # Bert-E shouldn't instruct to edit any w/ integration branch
            self.assertIn('on **the feature branch** '
                          '(`bugfix/TEST-0006-other`', e.msg)
            self.assertNotIn("w/",
                             e.msg)
        else:
            self.fail("No conflict detected.")

        try:
            self.handle(pr3.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                'between your branch `improvement/TEST-0006` and the\n'
                'destination branch `development/6.0`',
                e.msg)
            # Bert-E shouldn't instruct to edit any w/ integration branch
            self.assertIn('on **the feature branch** (`improvement/TEST-0006`',
                          e.msg)
            self.assertNotIn("w/", e.msg)
        else:
            self.fail("No conflict detected.")

        try:
            self.handle(pr4.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                '`w/6.0/improvement/TEST-0006-other` with contents from '
                '`improvement/TEST-0006-other`\nand `development/6.0`',
                e.msg)
            # Bert-E MUST instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn("git checkout -B w/6.0/improvement/TEST-0006", e.msg)
            self.assertIn("git merge origin/improvement/TEST-0006", e.msg)
            self.assertIn("git push -u origin w/6.0/improvement/TEST-0006",
                          e.msg)
        else:
            self.fail("No conflict detected.")

        # Check that the empty w/6.0 branch of pr4 wasn't pushed.
        self.assertFalse(self.gitrepo.remote_branch_exists(
            "w/6.0/improvement/TEST-0006-other", True))

        try:
            self.handle(pr5.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                '`w/6.0/improvement/TEST-0006-last` with contents from '
                '`w/5.1/improvement/TEST-0006-last`\nand `development/6.0`',
                e.msg)
            # Bert-E MUST instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn("git checkout -B w/6.0/improvement/TEST-0006", e.msg)
            self.assertIn("git merge origin/w/5.1/improvement/TEST-0006",
                          e.msg)
            self.assertIn("git push -u origin w/6.0/improvement/TEST-0006",
                          e.msg)
        else:
            self.fail("No conflict detected.")

        # Check that the empty w/6.0 branch of pr5 wasn't pushed.
        self.assertFalse(self.gitrepo.remote_branch_exists(
            "w/6.0/improvement/TEST-0006-last", True))

        # But that the w/5.1 branch of pr5 was.
        self.assertTrue(self.gitrepo.remote_branch_exists(
            "w/5.1/improvement/TEST-0006-last", True))

    def test_approvals(self):
        """Test approvals of author, reviewer and leader."""
        feature_branch = 'bugfix/TEST-0007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        github = self.args.git_host == 'github'

        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # Github doesn't support author approvals
        if not github:
            self.assertIn('the author', raised.exception.msg)

        self.assertIn('2 peers', raised.exception.msg)
        self.assertIn('*must* include a mandatory approval from @%s.' %
                      self.args.admin_username, raised.exception.msg)
        self.assertNotIn('*must* include at least', raised.exception.msg)

        # test approval on sub pr has not effect
        pr_child = self.admin_bb.get_pull_request(pull_request_id=pr.id + 1)
        pr_child.approve()
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id + 1, options=['bypass_jira_check'],
                        backtrace=True)

        # Check that a message was posted on the main PR, not the integration
        # PR
        self.assertEqual(list(pr_child.get_comments()), [])
        comment = list(pr.get_comments())[-1]

        if not github:
            self.assertIn('the author', comment.text)

        self.assertIn('2 peers', comment.text)
        self.assertIn('*must* include a mandatory approval from @%s.' %
                      self.args.admin_username, raised.exception.msg)
        self.assertNotIn('*must* include at least', raised.exception.msg)

        # test message with a single peer approval required
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
admins:
  - {admin}
project_leaders:
  - should_not_be_mentionned
""" # noqa
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)

        if not github:
            self.assertIn('the author', raised.exception.msg)
        self.assertIn('one peer', raised.exception.msg)
        self.assertNotIn('2 peers', raised.exception.msg)
        self.assertNotIn('*must* include a mandatory', raised.exception.msg)
        self.assertNotIn('*must* include at least', raised.exception.msg)
        self.assertNotIn('should_not_be_mentionned', raised.exception.msg)

        # test message with single mandatory approval required
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 3
admins:
  - {admin}
project_leaders:
  - dummy_leader_handle
""" # noqa
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        if not github:
            self.assertIn('the author', raised.exception.msg)
        self.assertIn('3 peers', raised.exception.msg)
        self.assertIn('*must* include a mandatory approval from '
                      '@dummy_leader_handle', raised.exception.msg)
        self.assertNotIn('*must* include at least', raised.exception.msg)

        # test message with multiple mandatory approvals required
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 3
required_peer_approvals: 3
admins:
  - {admin}
project_leaders:
  - dummy_leader_handle_1
  - dummy_leader_handle_2
  - dummy_leader_handle_3
  - dummy_leader_handle_4
""" # noqa
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        if not github:
            self.assertIn('the author', raised.exception.msg)
        self.assertIn('3 peers', raised.exception.msg)
        self.assertNotIn('*must* include a mandatory', raised.exception.msg)
        self.assertIn('*must* include at least 3 approvals from the '
                      'following list', raised.exception.msg)
        self.assertIn('* @dummy_leader_handle_1', raised.exception.msg)
        self.assertIn('* @dummy_leader_handle_2', raised.exception.msg)
        self.assertIn('* @dummy_leader_handle_3', raised.exception.msg)
        self.assertIn('* @dummy_leader_handle_4', raised.exception.msg)

        if github:
            # Stop here for github as author approval is deactivated
            return

        # test message with no peer approval required
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
""" # noqa
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        self.assertIn('the author', raised.exception.msg)
        self.assertNotIn('peer', raised.exception.msg)
        self.assertNotIn('*must* include a mandatory', raised.exception.msg)
        self.assertNotIn('*must* include at least', raised.exception.msg)

    def test_branches_creation_main_pr_not_approved(self):
        """Test if Bert-e creates integration pull-requests when the main
        pull-request isn't approved.

        1. Create feature branch and create an unapproved pull request
        2. Run Bert-E on the pull request
        3. Check existence of integration branches

        """
        for feature_branch in ['bugfix/TEST-0008', 'bugfix/TEST-0008-label']:
            dst_branch = 'stabilization/4.3.18'
            pr = self.create_pr(feature_branch, dst_branch)
            with self.assertRaises(exns.ApprovalRequired):
                self.handle(pr.id, options=['bypass_jira_check'],
                            backtrace=True)

            # check existence of integration branches
            for version in ['4.3', '5.1', '6.0']:
                remote = 'w/%s/%s' % (version, feature_branch)
                ret = self.gitrepo.remote_branch_exists(remote, True)
                self.assertTrue(ret)

            # check absence of a missing branch
            self.assertFalse(self.gitrepo.remote_branch_exists(
                'missing_branch'))

    def test_from_unrecognized_source_branch(self):
        for source in ['master2',
                       'feaure/TEST-12345']:
            create_branch(self.gitrepo, source,
                          from_branch='development/4.3', file_=True)
            pr = self.contributor_bb.create_pull_request(
                title='title',
                name='name',
                src_branch=source,
                dst_branch='development/4.3',
                close_source_branch=True,
                description=''
            )
            with self.assertRaises(exns.UnrecognizedBranchPattern):
                self.handle(pr.id, backtrace=True)

    def test_inclusion_of_jira_issue(self):
        pr = self.create_pr('bugfix/00066', 'development/4.3')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/00067', 'development/6.0')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('improvement/i', 'development/4.3')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/free_text', 'development/6.0')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/free_text2', 'stabilization/6.0.0')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/RONG-0001', 'development/6.0')
        with self.assertRaises(exns.IncorrectJiraProject):
            self.handle(pr.id, backtrace=True)

    def test_to_unrecognized_destination_branch(self):
        create_branch(self.gitrepo, 'master2',
                      from_branch='development/4.3', file_=True)
        create_branch(self.gitrepo, 'bugfix/TEST-00001',
                      from_branch='development/4.3', file_=True)
        pr = self.contributor_bb.create_pull_request(
            title='title',
            name='name',
            src_branch='bugfix/TEST-00001',
            dst_branch='master2',
            close_source_branch=True,
            description=''
        )
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.handle(pr.id, backtrace=True)

    def test_main_pr_retrieval(self):
        # create integration PRs first:
        pr = self.create_pr('bugfix/TEST-00066', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # simulate a child pr update
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id + 1, options=self.bypass_all, backtrace=True)

    def test_norepeat_strategy(self):
        def get_last_comment(pr):
            """Helper function to get the last comment of a pr.

            returns the md5 digest of the last comment for easier comparison.

            """
            return md5(list(pr.get_comments())[-1].text.encode()).digest()

        pr = self.create_pr('bugfix/TEST-01334', 'development/4.3',
                            file_='toto.txt')

        # Let Bert-E post its initial 'Hello' comment
        self.handle(pr.id)

        # The help message should be displayed every time the user requests it
        help_msg = ''
        pr.add_comment('@%s help' % self.args.robot_username)
        try:
            self.handle(pr.id, backtrace=True)
        except exns.HelpMessage as ret:
            help_msg = md5(ret.msg.encode()).digest()

        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, help_msg,
                         "Robot didn't post the first help message.")

        pr.add_comment("Ok, ok")
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, help_msg,
                            "message wasn't recorded.")

        pr.add_comment('@%s help' % self.args.robot_username)
        self.handle(pr.id)
        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, help_msg,
                         "Robot didn't post a second help message.")

        # Let's have Bert-E yield an actual AuthorApproval error message
        author_msg = ''
        try:
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        except exns.ApprovalRequired as ret:
            author_msg = md5(ret.msg.encode()).digest()

        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, author_msg,
                         "Robot didn't post his first error message.")

        pr.add_comment("OK, I Fixed it")
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, author_msg,
                            "message wasn't recorded.")

        # Bert-E should not repeat itself if the error is not fixed
        self.handle(pr.id, options=['bypass_jira_check'])
        last_comment = get_last_comment(pr)
        self.assertNotEqual(last_comment, author_msg,
                            "Robot repeated an error message when he "
                            "shouldn't have.")

        # Confront Bert-E to a different error (PeerApproval)
        self.handle(pr.id,
                    options=['bypass_jira_check', 'bypass_author_approval'])

        # Re-produce the AuthorApproval error, Bert-E should re-send the
        # AuthorApproval message
        self.handle(pr.id, options=['bypass_jira_check'])
        last_comment = get_last_comment(pr)
        self.assertEqual(last_comment, author_msg,
                         "Robot didn't respond to second occurrence of the "
                         "error.")

    def test_force_reset_command_with_history_mismatch(self):
        feature_branch = 'bugfix/TEST-00001'
        integration_branch = 'w/5.1/bugfix/TEST-00001'
        pr = self.create_pr(feature_branch, 'development/4.3')
        self.handle(pr.id, options=['bypass_jira_check'])
        pr.add_comment("@{} reset".format(self.args.robot_username))
        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, integration_branch,
                           'file_added_on_int_branch')
        with self.assertRaises(exns.LossyResetWarning):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # Try force reset
        pr.add_comment("@{} force_reset".format(self.args.robot_username))
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # Check that the work resumed normally
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_reset_command(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.handle(pr.id, options=['bypass_jira_check'])

        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('touch toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit --amend -m "Modified commit"')
        self.gitrepo.cmd('git push -f')

        pr.add_comment("@{} reset".format(self.args.robot_username))

        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # Check what happens if doing it again
        pr.add_comment("@{} reset".format(self.args.robot_username))
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, backtrace=True)

    def test_reset_command_with_deep_rebase(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('touch toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "Original commit 1"')
        self.gitrepo.cmd('touch tata.txt')
        self.gitrepo.cmd('git add tata.txt')
        self.gitrepo.cmd('git commit -m "Original commit 2"')
        self.gitrepo.cmd('touch tutu.txt')
        self.gitrepo.cmd('git add tutu.txt')
        self.gitrepo.cmd('git commit -m "Original commit 3"')
        self.gitrepo.cmd('git push origin bugfix/TEST-00001')

        self.handle(pr.id, options=['bypass_jira_check'])

        # Now rebase (reset hard + create a new commit)
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('git reset --hard HEAD~2')
        self.gitrepo.cmd('touch titi.txt')
        self.gitrepo.cmd('git add titi.txt')
        self.gitrepo.cmd('git commit -m "New commit"')
        self.gitrepo.cmd('git push -f')

        pr.add_comment("@{} reset".format(self.args.robot_username))

        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_reset_command_with_development_branch_update(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('touch toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "Original commit 1"')
        self.gitrepo.cmd('touch tata.txt')
        self.gitrepo.cmd('git add tata.txt')
        self.gitrepo.cmd('git commit -m "Original commit 2"')
        self.gitrepo.cmd('touch tutu.txt')
        self.gitrepo.cmd('git add tutu.txt')
        self.gitrepo.cmd('git commit -m "Original commit 3"')
        self.gitrepo.cmd('git push origin bugfix/TEST-00001')

        self.handle(pr.id, options=['bypass_jira_check'])

        # Merge another PR onto the development branches
        pr2 = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        self.handle(pr2.id, options=self.bypass_all)

        # Now rebase the feature branch onto development/4.3 and do a reset
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/4.3')
        self.gitrepo.cmd('git pull origin development/4.3')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('git rebase development/4.3')
        self.gitrepo.cmd('git reset --hard HEAD~2')
        self.gitrepo.cmd('touch titi.txt')
        self.gitrepo.cmd('git add titi.txt')
        self.gitrepo.cmd('git commit -m "New commit"')
        self.gitrepo.cmd('git push -f')

        pr.add_comment("@{} reset".format(self.args.robot_username))

        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_reset_command_with_deep_rebase_and_wbranch_update(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('touch toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "Original commit 1"')
        self.gitrepo.cmd('touch tata.txt')
        self.gitrepo.cmd('git add tata.txt')
        self.gitrepo.cmd('git commit -m "Original commit 2"')
        self.gitrepo.cmd('touch tutu.txt')
        self.gitrepo.cmd('git add tutu.txt')
        self.gitrepo.cmd('git commit -m "Original commit 3"')
        self.gitrepo.cmd('git push origin bugfix/TEST-00001')

        self.handle(pr.id, options=['bypass_jira_check'])

        # Add a manual commit on one of the integration branches
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/TEST-00001')
        self.gitrepo.cmd('echo plop > toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "Integration commit 1"')
        self.gitrepo.cmd('git push origin w/6.0/bugfix/TEST-00001')

        # Now rebase (reset hard + create a new commit)
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('git reset --hard HEAD~2')
        self.gitrepo.cmd('touch titi.txt')
        self.gitrepo.cmd('git add titi.txt')
        self.gitrepo.cmd('git commit -m "New commit"')
        self.gitrepo.cmd('git push -f')

        pr.add_comment("@{} reset".format(self.args.robot_username))

        with self.assertRaises(exns.LossyResetWarning):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_reset_command_and_bb_fails(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.handle(pr.id, options=['bypass_jira_check'])

        def fake_decline(self):
            raise Exception("couldn't decline")

        decline_real = type(pr).decline
        type(pr).decline = fake_decline

        try:
            pr.add_comment("@{} reset".format(self.args.robot_username))
            try:
                self.handle(pr.id, options=['bypass_jira_check'],
                            backtrace=True)
            except exns.ResetComplete as err:
                self.assertIn("I couldn't decline", err.msg)
        finally:
            type(pr).decline = decline_real

    def test_force_reset_command(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.handle(pr.id, options=['bypass_jira_check'])
        pr.add_comment("@{} force_reset".format(self.args.robot_username))
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_options_and_commands(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')

        # option: wait
        comment = pr.add_comment('@%s wait' % self.args.robot_username)
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, backtrace=True)
        comment.delete()

        # command: create_pull_requests
        pr.add_comment('@%s create_pull_requests' % self.args.robot_username)
        self.handle(pr.id)

        # command: build
        pr.add_comment('@%s build' % self.args.robot_username)
        with self.assertRaises(exns.CommandNotImplemented):
            self.handle(pr.id, backtrace=True)

        # command: clear
        pr.add_comment('@%s clear' % self.args.robot_username)
        with self.assertRaises(exns.CommandNotImplemented):
            self.handle(pr.id, backtrace=True)

        # command: status
        pr.add_comment('@%s status' % self.args.robot_username)
        with self.assertRaises(exns.StatusReport):
            self.handle(pr.id, backtrace=True)

        # command: status and garbage
        pr.add_comment('@%s status some arguments --hehe' %
                       self.args.robot_username)
        with self.assertRaises(exns.StatusReport):
            self.handle(pr.id, backtrace=True)

        # command: reset
        pr.add_comment('@%s reset' %
                       self.args.robot_username)
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, backtrace=True)

        # command: reset and garbage
        pr.add_comment('@%s reset some arguments --hehe' %
                       self.args.robot_username)
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, backtrace=True)

        # command: force reset
        pr.add_comment('@%s force_reset' %
                       self.args.robot_username)
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, backtrace=True)

        # command: force reset and garbage
        pr.add_comment('@%s force_reset some arguments --hehe' %
                       self.args.robot_username)
        with self.assertRaises(exns.ResetComplete):
            self.handle(pr.id, backtrace=True)

        # mix of option and command
        pr.add_comment('@%s unanimity' % self.args.robot_username)
        pr.add_comment('@%s status' % self.args.robot_username)
        with self.assertRaises(exns.StatusReport):
            self.handle(pr.id, backtrace=True)

        # test help command
        pr.add_comment('@%s help' % self.args.robot_username)
        with self.assertRaises(exns.HelpMessage):
            self.handle(pr.id, backtrace=True)

        # test help command with inter comment
        pr.add_comment('@%s: help' % self.args.robot_username)
        pr.add_comment('an irrelevant comment')
        with self.assertRaises(exns.HelpMessage):
            self.handle(pr.id, backtrace=True)

        # test help command with inter comment from Bert-E
        pr.add_comment('@%s help' % self.args.robot_username)
        pr_bert_e = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_bert_e.add_comment('this is my help already')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # test unknown command
        comment = pr.add_comment('@%s helpp' % self.args.robot_username)
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        # test command args
        pr.add_comment('@%s help some arguments --hehe' %
                       self.args.robot_username)
        with self.assertRaises(exns.HelpMessage):
            self.handle(pr.id, backtrace=True)

        # test incorrect address when setting options through comments
        pr.add_comment('@toto'  # toto is not Bert-E
                       ' bypass_author_approval'
                       ' bypass_peer_approval'
                       ' bypass_leader_approval'
                       ' bypass_build_status'
                       ' bypass_jira_check')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # test options set through deleted comment(self):
        comment = pr.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_leader_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % self.args.robot_username
        )
        comment.delete()
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

        # test no effect sub pr options
        sub_pr_admin = self.admin_bb.get_pull_request(
            pull_request_id=pr.id + 1)
        sub_pr_admin.add_comment('@%s'
                                 ' bypass_author_approval'
                                 ' bypass_peer_approval'
                                 ' bypass_build_status'
                                 ' bypass_jira_check' %
                                 self.args.robot_username)
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # test RELENG-1335: BertE unvalid status command

        feature_branch = 'bugfix/TEST-007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        pr.add_comment('@%s status?' % self.args.robot_username)
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_author_approval',
                            'bypass_leader_approval',
                            'bypass_peer_approval',
                        ],
                        backtrace=True)

    def test_bypass_options(self):
        # test bypass all approvals through an incorrect bitbucket comment
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_aproval'  # a p is missing
            ' bypass_peer_approval'
            ' bypass_leader_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % self.args.robot_username
        )
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        # test bypass all approvals through unauthorized bitbucket comment
        comment = pr.add_comment(
            '@%s'  # comment is made by unpriviledged user (robot itself)
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_leader_approval'
            ' bypass_build_status'
            ' bypass_jira_check' % self.args.robot_username
        )
        with self.assertRaises(exns.NotEnoughCredentials):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        # test bypass all approvals through an unknown bitbucket comment
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_leader_approval'
            ' bypass_build_status'
            ' mmm_never_seen_that_before'  # this is unknown
            ' bypass_jira_check' % self.args.robot_username
        )
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        # test approvals through a single bitbucket comment
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_leader_approval'
                             ' bypass_build_status'
                             ' bypass_jira_check' % self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)

        # test bypass all approvals through bitbucket comment extra spaces
        pr = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('  @%s  '
                             '   bypass_author_approval  '
                             '     bypass_peer_approval   '
                             ' bypass_leader_approval'
                             '  bypass_build_status'
                             '   bypass_jira_check' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)

        # test bypass all approvals through many comments
        pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_author_approval' %
                             self.args.robot_username)
        pr_admin.add_comment('@%s bypass_peer_approval' %
                             self.args.robot_username)
        pr_admin.add_comment('@%s bypass_leader_approval' %
                             self.args.robot_username)
        pr_admin.add_comment('@%s bypass_build_status' %
                             self.args.robot_username)
        pr_admin.add_comment('@%s bypass_jira_check' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)

        # test bypass all approvals through mix comments and cmdline
        pr = self.create_pr('bugfix/TEST-00004', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_leader_approval' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=['bypass_build_status', 'bypass_jira_check'],
                        backtrace=True)

        # test bypass author approval through comment
        pr = self.create_pr('bugfix/TEST-00005', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id, options=self.bypass_all_but(['bypass_author_approval']),
                backtrace=True
            )

        # test bypass peer approval through comment
        pr = self.create_pr('bugfix/TEST-00006', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_peer_approval' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_author_approval',
                            'bypass_leader_approval',
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        backtrace=True)

        # test bypass leader approval through comment
        pr = self.create_pr('bugfix/TEST-00007', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_leader_approval' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_author_approval',
                            'bypass_peer_approval',
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        backtrace=True)

        # test bypass jira check through comment
        pr = self.create_pr('bugfix/TEST-00008', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_jira_check' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_author_approval',
                            'bypass_leader_approval',
                            'bypass_peer_approval',
                            'bypass_build_status',
                        ],
                        backtrace=True)

        # test bypass build status through comment
        pr = self.create_pr('bugfix/TEST-00009', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_build_status' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test options lost in many comments
        pr = self.create_pr('bugfix/TEST-00010', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        for i in range(5):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_author_approval' %
                             self.args.robot_username)
        for i in range(6):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_peer_approval' %
                             self.args.robot_username)
        for i in range(3):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_build_status' %
                             self.args.robot_username)
        for i in range(22):
            pr.add_comment('random comment %s' % i)
        pr_admin.add_comment('@%s bypass_jira_check' %
                             self.args.robot_username)
        for i in range(10):
            pr.add_comment('random comment %s' % i)
        for i in range(10):
            pr.add_comment('@%s bypass_leader_approval' % i)
        pr_admin.add_comment('@%s bypass_leader_approval' %
                             self.args.robot_username)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)

        # test bypass all approvals through bitbucket comment extra chars
        pr = self.create_pr('bugfix/TEST-00011', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s:'
                             'bypass_author_approval,  '
                             '     bypass_peer_approval,,   '
                             ' bypass_leader_approval'
                             '  bypass_build_status-bypass_jira_check' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)

        # test bypass branch prefix through comment
        pr = self.create_pr('feature/TEST-00012', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_incompatible_branch' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_incompatible_branch']),
                backtrace=True)

    def test_rebased_feature_branch(self):
        pr = self.create_pr('bugfix/TEST-00074', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # create another PR and merge it entirely
        pr2 = self.create_pr('bugfix/TEST-00075', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        rebase_branch(self.gitrepo, 'bugfix/TEST-00075', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_first_integration_branch_manually_updated(self):
        feature_branch = 'bugfix/TEST-0076'
        first_integration_branch = 'w/5.1/bugfix/TEST-0076'
        pr = self.create_pr(feature_branch, 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')

        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

    def test_branches_not_self_contained(self):
        """Check that we can detect malformed git repositories."""
        feature_branch = 'bugfix/TEST-0077'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        add_file_to_branch(self.gitrepo, 'development/4.3',
                           'file_pushed_without_bert-e.txt', do_push=True)

        with self.assertRaises(exns.DevBranchesNotSelfContained):
            self.handle(pr.id, options=self.bypass_all)

    def test_missing_development_branch(self):
        """Check that we can detect malformed git repositories."""
        feature_branch = 'bugfix/TEST-0077'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)
        self.gitrepo.cmd('git push origin :development/6.0')

        with self.assertRaises(exns.DevBranchDoesNotExist):
            self.handle(pr.id, options=self.bypass_all)

    def test_wrong_pr_destination(self):
        """Check what happens if a PR's destination doesn't exist anymore."""
        pr = self.create_pr('bugfix/TEST-01', 'development/5.1')

        self.gitrepo.cmd('git push origin :development/5.1')

        with self.assertRaises(exns.WrongDestination):
            self.handle(pr.id, backtrace=True)

    def test_pr_skew_with_lagging_pull_request_data(self):
        # create hook
        try:
            real = gwf.create_integration_pull_requests
            global local_child_prs
            local_child_prs = []

            def _create_pull_requests(*args, **kwargs):
                global local_child_prs
                child_prs = real(*args, **kwargs)
                local_child_prs = child_prs
                return child_prs

            gwf.create_integration_pull_requests = _create_pull_requests

            pr = self.create_pr('bugfix/TEST-00081', 'development/6.0')
            # First pass on the PR to check build status is expected
            with self.assertRaises(exns.BuildNotStarted):
                self.handle(pr.id,
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

            # Set build status on child pr
            self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')

            # Add a new commit
            self.gitrepo.cmd('git checkout bugfix/TEST-00081')
            self.gitrepo.cmd('touch abc')
            self.gitrepo.cmd('git add abc')
            self.gitrepo.cmd('git commit -m "add new file"')
            self.gitrepo.cmd('git push origin')

            # now simulate a late bitbucket
            def _create_pull_requests2(*args, **kwargs):
                global local_child_prs
                return local_child_prs

            gwf.create_integration_pull_requests = _create_pull_requests2

            # Run Bert-E
            with self.assertRaises(exns.BuildNotStarted):
                self.handle(pr.id,
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

        finally:
            gwf.create_integration_pull_requests = real

    def test_pr_skew_with_new_external_commit(self):
        pr = self.create_pr('bugfix/TEST-00081', 'development/5.1')
        # Create integration branch and child pr
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # Set build status
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')

        # create hook
        try:
            real = gwf.create_integration_pull_requests

            def _create_pull_requests(*args, **kwargs):
                # simulate the update of the integration PR (by addition
                # of a commit) by another process, (typically a user),
                # in between the start of Bert-E and his decision to merge
                self.gitrepo.cmd('git fetch')
                self.gitrepo.cmd('git checkout w/6.0/bugfix/TEST-00081')
                self.gitrepo.cmd('touch abc')
                self.gitrepo.cmd('git add abc')
                self.gitrepo.cmd('git commit -m "add new file"')
                self.gitrepo.cmd('git push origin')
                sha1 = self.gitrepo.cmd(
                    'git rev-parse w/6.0/bugfix/TEST-00081')

                child_prs = real(*args, **kwargs)
                if TestBertE.args.git_host != 'mock':
                    # make 100% sure the PR is up-to-date (since BB lags):
                    child_prs[0].src_commit = sha1
                return child_prs

            gwf.create_integration_pull_requests = _create_pull_requests

            # Run Bert-E
            with self.assertRaises(exns.PullRequestSkewDetected):
                self.handle(pr.id,
                            options=self.bypass_all_but(
                                ['bypass_build_status']),
                            backtrace=True)

        finally:
            gwf.create_integration_pull_requests = real

    def test_build_status(self):
        pr = self.create_pr('bugfix/TEST-00081', 'development/4.3')

        # test build not started
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test non related build key
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL',
                                       key='pipelin')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL',
                                       key='pipelin')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL',
                                       key='pipelin')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test build status failed
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr.id + 2, 'FAILED')
        try:
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        except exns.BuildFailed as excp:
            self.assertIn(
                "did not succeed in branch w/6.0/bugfix/TEST-00081",
                excp.msg,
            )
        else:
            raise Exception('did not raise BuildFailed')

        # test build status inprogress
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')
        with self.assertRaises(exns.BuildInProgress):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test bypass leader approval through comment
        pr = self.create_pr('bugfix/TEST-00078', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_leader_approval' %
                             self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_author_approval',
                            'bypass_peer_approval',
                            'bypass_jira_check',
                            'bypass_build_status'],
                        backtrace=True)

    def test_build_status_triggered_by_build_result(self):
        pr = self.create_pr('bugfix/TEST-00081', 'development/5.1')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        self.set_build_status_on_pr_id(
            pr.id, 'FAILED',
            # github enforces valid build urls
            url='https://builds/test.com/DEADBEEF'
        )
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')

        with self.assertRaises(exns.BuildFailed) as err:
            childpr = self.robot_bb.get_pull_request(
                pull_request_id=pr.id + 1)
            self.handle(childpr.src_commit,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
            self.assertIn('https://builds/test.com/DEADBEEF', err.msg)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(childpr.src_commit,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

    def test_source_branch_history_changed(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        # see what happens when the source branch is deleted
        self.gitrepo.cmd('git checkout development/4.3')
        self.gitrepo.cmd('git push origin :bugfix/TEST-00001')
        self.gitrepo.cmd('git branch -D bugfix/TEST-00001')
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id,
                        options=self.bypass_all,
                        backtrace=True)
        # recreate branch with a different history
        create_branch(self.gitrepo, 'bugfix/TEST-00001',
                      from_branch='development/4.3', file_="a_new_file")
        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

    def test_source_branch_commit_added_and_target_updated(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        pr2 = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # Source branch is modified
        add_file_to_branch(self.gitrepo, 'bugfix/TEST-00001', 'some_file')
        # Another PR is merged
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_source_branch_commit_added(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        add_file_to_branch(self.gitrepo, 'bugfix/TEST-00001',
                           'file_added_on_source_branch')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_source_branch_forced_pushed(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
        create_branch(self.gitrepo, 'bugfix/TEST-00002',
                      from_branch='development/4.3',
                      file_="another_new_file", do_push=False)
        self.gitrepo.cmd(
            'git push -u -f origin bugfix/TEST-00002:bugfix/TEST-00001')
        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_integration_branch_and_source_branch_updated(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)
        first_integration_branch = 'w/5.1/bugfix/TEST-00001'
        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')
        add_file_to_branch(self.gitrepo, 'bugfix/TEST-00001',
                           'file_added_on_source_branch')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_integration_branch_and_source_branch_force_updated(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)
        first_integration_branch = 'w/5.1/bugfix/TEST-00001'
        self.gitrepo.cmd('git pull')
        add_file_to_branch(self.gitrepo, first_integration_branch,
                           'file_added_on_int_branch')
        create_branch(self.gitrepo, 'bugfix/TEST-00002',
                      from_branch='development/4.3',
                      file_="another_new_file", do_push=False)
        self.gitrepo.cmd(
            'git push -u -f origin bugfix/TEST-00002:bugfix/TEST-00001')
        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def successful_merge_into_stabilization_branch(self, branch_name,
                                                   expected_dest_branches):
        pr = self.create_pr('bugfix/TEST-00001', branch_name)
        self.handle(pr.id, options=self.bypass_all)
        self.gitrepo.cmd('git pull -a --prune')
        expected_result = set(expected_dest_branches)
        result = set(self.gitrepo
                     .cmd('git branch -r --contains origin/bugfix/TEST-00001')
                     .replace(" ", "").split('\n')[:-1])
        self.assertEqual(expected_result, result)

    def test_successful_merge_into_stabilization_branch(self):
        dest = 'stabilization/4.3.18'
        res = ["origin/bugfix/TEST-00001",
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
        res = ["origin/bugfix/TEST-00001",
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
        pr = self.create_pr('bugfix/TEST-00001', 'stabilization/5.1.4')
        try:
            self.handle(pr.id, options=[
                'bypass_build_status',
                'bypass_leader_approval',
                'bypass_peer_approval',
                'bypass_author_approval'],
                backtrace=True)
        except exns.SuccessMessage as e:
            self.assertIn('* :heavy_check_mark: `stabilization/5.1.4`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/5.1`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/6.0`', e.msg)
            self.assertIn('* `stabilization/4.3.18`', e.msg)
            self.assertIn('* `stabilization/6.0.0`', e.msg)
            self.assertIn('* `development/4.3`', e.msg)

    def test_unanimity_option(self):
        """Test unanimity by passing option to bert-e"""

        if self.args.git_host == 'github':
            self.skipTest("Unanimity doesn't work on GitHub")

        feature_branch = 'bugfix/TEST-0076'
        dst_branch = 'development/4.3'
        reviewers = [self.creator]

        pr = self.create_pr(feature_branch, dst_branch,
                            reviewers=reviewers)
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id,
                        options=self.bypass_all + ['unanimity'],
                        backtrace=True)
        self.assertIn('author', raised.exception.msg)
        self.assertIn('peer', raised.exception.msg)
        self.assertIn('unanimity', raised.exception.msg)

    def test_unanimity_required_all_approval(self):
        """Test unanimity with all approval required"""

        if self.args.git_host == 'github':
            self.skipTest("Unanimity doesn't work on GitHub")

        feature_branch = 'bugfix/TEST-007'
        dst_branch = 'development/4.3'

        pr = self.create_pr(feature_branch, dst_branch)

        pr.add_comment('@%s unanimity' % self.args.robot_username)

        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        self.assertIn('unanimity', raised.exception.msg)

        # Author adds approval
        pr.approve()
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        self.assertIn('unanimity', raised.exception.msg)

        # 1st reviewer adds approval (project leader)
        pr_peer = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_peer.approve()
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        self.assertIn('unanimity', raised.exception.msg)

        # 2nd reviewer adds approval
        pr_peer = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()
        with self.assertRaises(exns.SuccessMessage) as raised:
            self.handle(pr.id,
                        options=['bypass_jira_check',
                                 'bypass_build_status'],
                        backtrace=True)

    def test_after_pull_request(self):
        pr_opened = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        pr_declined = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        pr_declined.decline()
        blocked_pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')

        comment_declined = blocked_pr.add_comment(
            '@%s after_pull_request=%s' % (
                self.args.robot_username,
                pr_declined.id))

        with self.assertRaises(exns.AfterPullRequest):
            self.handle(blocked_pr.id, options=self.bypass_all, backtrace=True)

        blocked_pr.add_comment('@%s after_pull_request=%s' % (
            self.args.robot_username, pr_opened.id))

        with self.assertRaises(exns.AfterPullRequest):
            self.handle(blocked_pr.id, options=self.bypass_all, backtrace=True)

        comment_declined.delete()
        with self.assertRaises(exns.AfterPullRequest):
            self.handle(blocked_pr.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr_opened.id, options=self.bypass_all, backtrace=True)

        if self.args.git_host != 'mock':
            # take bitbucket laggyness into account
            time.sleep(10)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(blocked_pr.id, options=self.bypass_all,
                        backtrace=True)

    def test_after_pull_request_wrong_syntax(self):
        pr_declined = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        pr_declined.decline()
        blocked_pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')

        blocked_pr.add_comment(
            '@%s after_pull_request %s' % (
                self.args.robot_username,
                pr_declined.id))

        with self.assertRaises(exns.IncorrectCommandSyntax):
            self.handle(blocked_pr.id, options=self.bypass_all, backtrace=True)

    def test_after_pull_request_wrong_pr_id(self):
        blocked_pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')

        blocked_pr.add_comment(
            '@%s after_pull_request=0' % (self.args.robot_username,))

        with self.assertRaises(exns.IncorrectPullRequestNumber):
            self.handle(blocked_pr.id, options=self.bypass_all, backtrace=True)

    def test_no_octopus_option(self):
        """Test no_octopus by passing option to bert-e."""
        octopus_branch = 'bugfix/TEST-octopus'
        no_octopus_branch = 'bugfix/TEST-no-octopus'
        dst_branch = 'development/4.3'

        class KrakenDisturbed(Exception):
            pass

        def disturb_the_kraken(dst, src1, src2):
            raise KrakenDisturbed()

        octopus_merge = git.octopus_merge
        git.octopus_merge = disturb_the_kraken

        try:
            # Check the merges are octopus without the option
            pr = self.create_pr(octopus_branch, dst_branch)
            with self.assertRaises(KrakenDisturbed):
                self.handle(pr.id,
                            options=self.bypass_all,
                            backtrace=True)

            # Now check the no_octopus option prevent octopus merges
            pr = self.create_pr(no_octopus_branch, dst_branch)
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id,
                            options=self.bypass_all + ['no_octopus'],
                            backtrace=True)
        finally:
            git.octopus_merge = octopus_merge

    def test_fallback_to_consecutive_merge(self):
        def disturb_the_kraken(dst, src1, src2):
            raise MergeFailedException()

        octopus_merge = git.octopus_merge
        git.octopus_merge = disturb_the_kraken

        try:
            pr = self.create_pr('bugfix/test-merge', 'development/4.3')
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id, options=self.bypass_all, backtrace=True)
        finally:
            git.octopus_merge = octopus_merge

    def test_robust_merge(self):
        """Simulate a successful incorrect octopus merge.

        Check that the PR was still correctly merged
        (using sequential strategy).

        """
        octopus_merge = git.octopus_merge

        sha1 = None

        def wrong_octopus_merge(dst, src1, src2):
            octopus_merge(dst, src1, src2)
            dst.checkout()
            dst.repo.cmd('echo plop >> tmp')
            dst.repo.cmd('git add tmp')
            dst.repo.cmd('git commit -m "extra commit"')
            nonlocal sha1
            sha1 = dst.repo.cmd('git log -n 1 --pretty="%H"')

        git.octopus_merge = wrong_octopus_merge

        try:
            pr = self.create_pr('bugfix/test-merge', 'development/4.3')
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id, options=self.bypass_all, backtrace=True)

            assert sha1 is not None  # the function was called

            self.gitrepo.cmd('git fetch --prune')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/development/4.3 '
                             'origin/development/6.0')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/bugfix/test-merge '
                             'origin/development/4.3')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/bugfix/test-merge '
                             'origin/development/6.0')

            with self.assertRaises(CommandError):
                self.gitrepo.cmd('git merge-base --is-ancestor {} '
                                 'origin/development/6.0'
                                 .format(sha1))
        finally:
            git.octopus_merge = octopus_merge

    def test_bitbucket_lag_on_pr_status(self):
        """Bitbucket can be a bit long to update a merged PR's status.

        Check that Bert-E handles this case nicely and returns before creating
        integration PRs.

        """
        try:
            real = gwf.early_checks

            pr = self.create_pr('bugfix/TEST-00081', 'development/6.0')
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id, self.bypass_all, backtrace=True)

            gwf.early_checks = lambda *args, **kwargs: None

            with self.assertRaises(exns.NothingToDo):
                self.handle(pr.id, self.bypass_all, backtrace=True)

        finally:
            gwf.early_checks = real

    def test_pr_title_too_long(self):
        create_branch(self.gitrepo, 'bugfix/TEST-00001',
                      from_branch='development/4.3', file_=True)
        pr = self.contributor_bb.create_pull_request(
            title='A' * bitbucket_api.MAX_PR_TITLE_LEN,
            name='name',
            src_branch='bugfix/TEST-00001',
            dst_branch='development/4.3',
            close_source_branch=True,
            description=''
        )

        with self.assertRaises(exns.SuccessMessage):
            try:
                self.handle(pr.id, options=self.bypass_all, backtrace=True)
            except requests.HTTPError as err:
                self.fail("Error from bitbucket: %s" % err.response.text)

    def test_main_pr_declined(self):
        """Check integration data (PR+branches) is deleted when original
        PR is declined."""
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # check integration data is there
        branches = self.gitrepo.cmd(
            'git ls-remote origin w/*/bugfix/TEST-00001')
        self.assertTrue(len(branches))
        pr_ = self.admin_bb.get_pull_request(pull_request_id=pr.id + 1)
        self.assertEqual(pr_.status, 'OPEN')
        pr_ = self.admin_bb.get_pull_request(pull_request_id=pr.id + 2)
        self.assertEqual(pr_.status, 'OPEN')

        pr.decline()
        with self.assertRaises(exns.PullRequestDeclined):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

        # check integration data is gone
        branches = self.gitrepo.cmd(
            'git ls-remote origin w/*/bugfix/TEST-00001')
        self.assertEqual(branches, '')
        pr_ = self.admin_bb.get_pull_request(pull_request_id=pr.id + 1)
        self.assertEqual(pr_.status, 'DECLINED')
        pr_ = self.admin_bb.get_pull_request(pull_request_id=pr.id + 2)
        self.assertEqual(pr_.status, 'DECLINED')

        # check nothing bad happens if called again
        with self.assertRaises(exns.NothingToDo):
            self.handle(
                pr.id,
                options=self.bypass_all_but(['bypass_build_status']),
                backtrace=True)

    def test_integration_pr_declined(self):
        pr = self.create_pr('bugfix/TEST-0001', 'development/4.3')
        self.gitrepo.cmd('git fetch --all')
        self.gitrepo.cmd('git checkout bugfix/TEST-0001')

        # Add another commit
        self.gitrepo.cmd('echo something > toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "something"')
        self.gitrepo.push('bugfix/TEST-0001')

        self.handle(
            pr.id, options=self.bypass_all_but(['bypass_build_status']))

        int_prs = list(self.contributor_bb.get_pull_requests(
            src_branch=[
                'w/5.1/bugfix/TEST-0001',
                'w/6.0/bugfix/TEST-0001'
            ])
        )

        self.gitrepo.cmd('git checkout bugfix/TEST-0001')
        self.gitrepo.cmd('git reset HEAD~1 --hard')
        self.gitrepo.cmd('git push origin -f bugfix/TEST-0001')

        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # Decline integration pull requests
        self.assertEqual(len(int_prs), 2)
        for ipr in int_prs:
            ipr.decline()

        # Delete integration branches
        self.gitrepo.push(':w/5.1/bugfix/TEST-0001 '
                          ':w/6.0/bugfix/TEST-0001')

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_branch_name_escape(self):
        """Make sure git api support branch names with
        special chars and doesn't interpret them in bash.

        """
        unescaped = 'bugfix/dangerous-branch-name-${TEST}'

        # Bypass git-api to create the branch (explicit escape of the bad char)
        branch_name = unescaped.replace('$', '\$')
        cmd('git checkout development/5.1', cwd=self.gitrepo.cmd_directory)
        cmd('git checkout -b %s' % branch_name, cwd=self.gitrepo.cmd_directory)

        # Check that the branch exists with its unescaped name and the git-api
        self.assertTrue(Branch(self.gitrepo, unescaped).exists())

    def test_input_tokens(self):
        with self.assertRaises(exns.UnsupportedTokenType):
            self.handle('toto', backtrace=True)

        with self.assertRaises(exns.UnsupportedTokenType):
            self.handle('1a2b3c', backtrace=True)  # short sha1

        with self.assertRaises(exns.UnsupportedTokenType):
            self.handle('/development/4.3', backtrace=True)

    def test_conflict_due_to_update_order(self):
        """Reproduce the case where a conflict coming from another Pull-Request
        (and ultimately fixed in the other Pull Request) triggers a conflict
        during the update of integration branches.

        """
        pr1 = self.create_pr('bugfix/TEST-0006', 'development/5.1',
                             file_='toto.txt')
        pr2 = self.create_pr('bugfix/TEST-0006-other', 'development/4.3',
                             file_='toto.txt')
        pr3 = self.create_pr('bugfix/TEST-0007-unrelated', 'development/4.3')

        self.handle(
            pr2.id, options=self.bypass_all_but(['bypass_author_approval']))

        # Merge the first Pull Request
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        self.handle(
            pr3.id, options=self.bypass_all_but(['bypass_author_approval']))

        # Conflict on branch 'w/5.1/bugfix/TEST-0006-other'
        try:
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as err:
            self.assertIn('`w/5.1/bugfix/TEST-0006-other` with', err.msg)
        else:
            self.fail('No conflict detected')

        # Resolve conflict
        self.gitrepo.cmd('git fetch --all')
        self.gitrepo.cmd('git checkout w/5.1/bugfix/TEST-0006-other')
        self.gitrepo.cmd('git merge origin/bugfix/TEST-0006-other')
        self.gitrepo.cmd('echo bugfix/TEST-0006 > toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "fix conflict"')
        self.gitrepo.cmd('git merge origin/development/5.1')
        self.gitrepo.push('w/5.1/bugfix/TEST-0006-other')

        # Conflict should be resolved and PR merged
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr3.id, options=self.bypass_all, backtrace=True)

    def test_settings(self):
        # test with no peer approvals set to 0
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
""" # noqa
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings
            )

        # test with incorrect settings file
        pr = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key
required_leader_approvals: 0
required_peer_approvals: 0
""" # noqa
        with self.assertRaises(exns.IncorrectSettingsFile):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings
            )

        # test with different build key
        pr = self.create_pr('bugfix/TEST-00003', 'development/6.0')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: toto
# comment
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
""" # noqa
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings)
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL', key='toto')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=['bypass_author_approval'],
                        settings=settings, backtrace=True)

        # test missing mandatory setting
        pr = self.create_pr('bugfix/TEST-00004', 'development/4.3')
        settings = """
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 2
admins:
  - {admin}
""" # noqa
        with self.assertRaises(exns.MalformedSettings):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings)

        # fail if required number of leader approvals greater than leaders
        pr = self.create_pr('bugfix/TEST-00005', 'development/4.3')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 2
required_peer_approvals: 2
admins:
  - {admin}
project_leaders:
  - {admin}
""" # noqa
        with self.assertRaises(exns.MalformedSettings):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings)

        # fail if peer approvals lower than leader approvals
        pr = self.create_pr('bugfix/TEST-00006', 'development/4.3')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 0
admins:
  - {admin}
project_leaders:
  - {admin}
""" # noqa
        with self.assertRaises(exns.MalformedSettings):
            self.handle(
                pr.id, options=['bypass_author_approval'], backtrace=True,
                settings=settings)

    def test_task_list_creation(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        pr = self.create_pr('feature/death-ray', 'development/6.0')
        try:
            self.handle(pr.id)
        except requests.HTTPError as err:
            self.fail("Error from bitbucket: %s" % err.response.text)
        # retrieving tasks from private bitbucket API only works for admin
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        self.assertEqual(len(list(pr_admin.get_tasks())), 2)
        init_comment = pr.comments[0].text
        self.assertIn('task', init_comment)

    def test_task_list_missing(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        pr = self.create_pr('feature/death-ray', 'development/6.0')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
""" # noqa
        try:
            self.handle(pr.id, settings=settings)
        except requests.HTTPError as err:
            self.fail("Error from bitbucket: %s" % err.response.text)
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        self.assertEqual(len(list(pr_admin.get_tasks())), 0)
        init_comment = pr.comments[0].text
        self.assertNotIn('task', init_comment)

    def test_task_list_funky(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        pr = self.create_pr('feature/death-ray', 'development/6.0')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
tasks:
  - ''
  - zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz
  - éâàë€
  - 1
  - 2
  - 3
  - 3
  - 3
  - 3
  - 3
  - 3
  - 3
  - 3
  - 3
  - 3
""" # noqa
        try:
            self.handle(pr.id, settings=settings)
        except requests.HTTPError as err:
            self.fail("Error from bitbucket: %s" % err.response.text)
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        self.assertEqual(len(list(pr_admin.get_tasks())), 15)

    def test_task_list_illegal(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        pr = self.create_pr('feature/death-ray', 'development/6.0')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
admins:
  - {admin}
tasks:
  - ['a task in a list']
""" # noqa
        with self.assertRaises(exns.MalformedSettings):
            self.handle(pr.id, backtrace=True, settings=settings)

    def test_task_list_incompatible_api_update_create(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        try:
            real = bitbucket_api.Task.add_url
            bitbucket_api.Task.add_url = 'https://bitbucket.org/plouf'

            pr = self.create_pr('feature/death-ray', 'development/6.0')
            try:
                self.handle(pr.id)
            except requests.HTTPError as err:
                self.fail("Error from bitbucket: %s" % err.response.text)
            pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
            self.assertEqual(len(list(pr_admin.get_tasks())), 0)

        finally:
            bitbucket_api.Task.add_url = real

    def test_task_list_incompatible_api_update_list(self):
        if self.args.git_host == 'github':
            self.skipTest("Tasks are not supported on GitHub")

        try:
            real = bitbucket_api.Task.list_url
            bitbucket_api.Task.list_url = 'https://bitbucket.org/plouf'

            pr = self.create_pr('feature/death-ray', 'development/6.0')
            try:
                self.handle(pr.id)
            except requests.HTTPError as err:
                self.fail("Error from bitbucket: %s" % err.response.text)
            pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
            with self.assertRaises(exns.TaskAPIError):
                len(list(pr_admin.get_tasks()))

        finally:
            bitbucket_api.Task.list_url = real

    def test_branches_have_diverged(self):
        settings = DEFAULT_SETTINGS + 'max_commit_diff: 5'
        pr = self.create_pr('feature/time-warp', 'development/6.0')

        for idx in range(6):
            tpr = self.create_pr('feature/%s' % idx, 'development/6.0')
            self.handle(tpr.id, options=self.bypass_all, settings=settings)

        with self.assertRaises(exns.SourceBranchTooOld):
            self.handle(pr.id, backtrace=True, settings=settings,
                        options=self.bypass_all)

    def test_development_branch_removal(self):
        """Check that Bert-E survives to the removal of a development branch.

        Steps:
            Create a PR targetting 4.3
            Let the robot create the integration cascade
            Add modifications to the w/5.1 integration branch
            Let the robot propagate the change to w/6.0
            Remove the development/5.1 and stabilization/5.1 branches
            Wake up the robot on the PR with bypass_all

        Expected result:
            The PR gets merged into development/4.3 and development/6.0

        """

        pr = self.create_pr('feature/foo', 'development/4.3')
        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # Add some changes to the w/5.1 integration branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/5.1/feature/foo')
        self.gitrepo.cmd('echo foo > foo')
        self.gitrepo.cmd('git add foo')
        self.gitrepo.cmd('git commit -m "add foo"')
        self.gitrepo.cmd('git push origin w/5.1/feature/foo')

        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        self.gitrepo.cmd('git checkout development/5.1')
        self.gitrepo.cmd('git tag 5.1.4')
        self.gitrepo.cmd(
            'git push origin :stabilization/5.1.4 :development/5.1 --tags')

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/4.3')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/6.0')

    def test_stabilization_branch_addition(self):
        """Check that Bert-E survives to the addition of a stab branch.

        Steps:
            Delete stabilization/6.0.0
            Create a PR targetting development/4.3
            Let the robot create the integration cascade
            Add a stabilization/6.0.0 branch
            Wake up the robot on the PR with bypass_all

        Expected result:
            The PR gets merged into development/4.3, development/5.1
            and development/6.0.

        """
        self.gitrepo.cmd('git push origin :stabilization/6.0.0')
        pr = self.create_pr('feature/foo', 'development/4.3')
        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # Create a stabilization/6.0.0 branch on top of development/6.0
        self.gitrepo.cmd('git fetch --prune')
        self.gitrepo.cmd('git checkout -B stabilization/6.0.0 development/6.0')
        self.gitrepo.cmd('git push -u origin stabilization/6.0.0')

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/4.3')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/5.1')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/6.0')

    def test_stabilization_and_dev_branch_addition(self):
        """Check that Bert-E survives to the addition of middle branches.

        Steps:
            Delete dev/5.1 and stab/5.1.4
            Create a PR targetting dev/4.3 and fully merge it
            Create a second PR targetting dev/4.3
            Let the robot create the integration cascade
            Add a dev/5.1 and stab/5.1.4 branch
            Wake up the robot on the PR with bypass_all

        Expected result:
            - BranchHistoryMismatch
            - When resetting the queues and adding a force_reset command,
            the second PR gets merged

        """
        self.gitrepo.cmd('git push origin '
                         ':stabilization/5.1.4 :development/5.1')
        pr = self.create_pr('feature/foo', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/4.3')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/6.0')

        pr = self.create_pr('feature/bar', 'development/4.3')
        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        self.gitrepo.cmd('git fetch --prune')
        self.gitrepo.cmd('git checkout -B development/5.1'
                         ' origin/development/4.3')
        self.gitrepo.cmd('git checkout -B stabilization/5.1.4'
                         ' development/5.1')
        self.gitrepo.cmd('git push -u origin '
                         'development/5.1 stabilization/5.1.4')

        if not self.args.disable_queues:
            self.gitrepo.cmd('git push origin :q/4.3 :q/6.0')

        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        pr.add_comment("@%s force_reset" % self.args.robot_username)
        self.handle(pr.id, options=self.bypass_all)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_merge_again_in_earlier_dev_branch(self):
        """Check Bert-E can handle merging again in an earlier dev branch.

        Steps:
            Create a PR targetting development/4.3
            Create another PR with same branch targetting development/5.1
            Merge the second PR with bypass_all
            Merge the first PR with bypass_all

        Expected result:
            Both PRs get merged and the commit is available in development/4.3,
            development/5.1 and development/6.0.

        """
        pr1 = self.create_pr('bugfix/TEST-0001', 'development/4.3')
        pr2 = self.create_pr('bugfix/TEST-0001', 'development/5.1',
                             reuse_branch=True)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

    def test_mandatory_approval(self):
        """Test a pull request does not merge without mandatory approvals."""

        # test mandatory approvals when author is project lead and does not
        # approve his own work, and author approval not expected
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: False
required_leader_approvals: 1
required_peer_approvals: 1
admins:
  - {admin}
project_leaders:
  - {contributor}
  - another_leader_handle
""" # noqa
        pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        pr_peer = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        # Github doesn't support author approvals
        if self.args.git_host == 'github':
            return

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 1
admins:
  - {admin}
project_leaders:
  - {admin}
""" # noqa
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        pr.approve()
        pr_peer = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        self.assertIn('one peer', raised.exception.msg)
        self.assertNotIn('2 peers', raised.exception.msg)
        self.assertIn('*must* include a mandatory approval from @%s.' %
                      self.args.admin_username, raised.exception.msg)

        pr_leader = self.admin_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_leader.approve()

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        # test mandatory approvals when author is project lead and does not
        # approve his own work
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot_username: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 1
admins:
  - {admin}
project_leaders:
  - {contributor}
  - another_leader_handle
""" # noqa
        pr = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        self.assertIn('one peer', raised.exception.msg)
        self.assertNotIn('2 peers', raised.exception.msg)
        self.assertIn('*must* include at least 1 approval from the '
                      'following list', raised.exception.msg)
        self.assertIn('* @%s' % self.args.contributor_username,
                      raised.exception.msg)
        self.assertIn('* @another_leader_handle', raised.exception.msg)

        pr_peer = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()

        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_author_approval',
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)


class TestQueueing(RepositoryTests):
    """Tests which validate all things related to the merge queue.

    Theses tests are skipped if --disable-queues is passed to the runner.

       http://xkcd.com/853/

    """
    def setUp(self):
        if self.args.disable_queues:
            self.skipTest("skipping queue-related tests, "
                          "remove --disable-queues to activate")
        super().setUp()

    def queue_branch(self, name):
        return gwfb.QueueBranch(self.gitrepo, name)

    def qint_branch(self, name):
        return gwfb.QueueIntegrationBranch(self.gitrepo, name)

    def submit_problem(self, problem, build_key='pipeline'):
        """Create a repository with dev, int and q branches ready."""
        self.admin_bb.invalidate_build_status_cache()
        for pr in problem.keys():
            pr_ = self.create_pr(problem[pr]['src'], problem[pr]['dst'])

            # run Bert-E until creation of q branches
            with self.assertRaises(exns.Queued):
                self.handle(pr_.id, options=self.bypass_all, backtrace=True)

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

            qbranches = [branch.format(pr=pr_.id, name=problem[pr]['src'])
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
        qc = gwfb.QueueCollection(
            self.robot_bb,
            'pipeline',
            merge_paths=[  # see initialize_git_repo
                [gwfb.branch_factory(FakeGitRepo(), 'development/4.3'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/5.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/6.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'stabilization/4.3.18'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/4.3'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/5.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/6.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'stabilization/5.1.4'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/5.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/6.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'stabilization/6.0.0'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/6.0')],
            ])
        for qbranch in qbranches:
            qc._add_branch(gwfb.branch_factory(self.gitrepo, qbranch))
        return qc

    def test_queue_branch(self):
        with self.assertRaises(exns.BranchNameInvalid):
            self.queue_branch("q/4.3/feature/RELENG-001-plop")

        qbranch = gwfb.branch_factory(FakeGitRepo(), "q/5.1")
        self.assertEqual(type(qbranch), gwfb.QueueBranch)
        self.assertEqual(qbranch.version, "5.1")
        self.assertEqual(qbranch.major, 5)
        self.assertEqual(qbranch.minor, 1)

    def test_qint_branch(self):
        with self.assertRaises(exns.BranchNameInvalid):
            self.qint_branch("q/6.3")

        with self.assertRaises(exns.BranchNameInvalid):
            self.qint_branch("q/6.2/feature/RELENG-001-plop")

        qint_branch = gwfb.branch_factory(FakeGitRepo(),
                                          "q/10/6.2/feature/RELENG-001-plop")
        self.assertEqual(type(qint_branch), gwfb.QueueIntegrationBranch)
        self.assertEqual(qint_branch.version, "6.2")
        self.assertEqual(qint_branch.pr_id, 10)
        self.assertEqual(qint_branch.major, 6)
        self.assertEqual(qint_branch.minor, 2)
        self.assertEqual(qint_branch.jira_project, 'RELENG')

    def test_queueing_no_queues_in_repo(self):
        qc = self.feed_queue_collection({})
        qc.finalize()
        qc.validate()
        self.assertEqual(qc.mergeable_prs, [])

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
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: []
            }),
            ('5.1', {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: []
            }),
            ('6.0', {
                gwfb.QueueBranch: self.queue_branch('q/6.0'),
                gwfb.QueueIntegrationBranch: []
            }),
        ])

    @property
    def standard_solution(self):
        """This is the solution to the standard problem."""
        return OrderedDict([
            ('4.3', {
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/4.3/improvement/bar2'),
                    self.qint_branch('q/1/4.3/improvement/bar')
                ]
            }),
            ('5.1', {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/5.1/improvement/bar2'),
                    self.qint_branch('q/5/5.1/bugfix/bar'),
                    self.qint_branch('q/1/5.1/improvement/bar')
                ]
            }),
            ('6.0', {
                gwfb.QueueBranch: self.queue_branch('q/6.0'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/6.0/improvement/bar2'),
                    self.qint_branch('q/5/6.0/bugfix/bar'),
                    self.qint_branch('q/4/6.0/feature/foo'),
                    self.qint_branch('q/1/6.0/improvement/bar')
                ]
            }),
        ])

    def test_queueing_standard_problem(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_queues, self.standard_solution)

    def test_queueing_standard_problem_reverse(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(reversed(qbranches))
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_queues, self.standard_solution)

    def test_queueing_standard_problem_without_octopus(self):
        # monkey patch to skip octopus merge in favor of regular 2-way merges
        gwfi.octopus_merge = git.consecutive_merge
        gwfq.octopus_merge = git.consecutive_merge

        try:
            qbranches = self.submit_problem(self.standard_problem)
            qc = self.feed_queue_collection(qbranches)
            qc.finalize()
            qc.validate()
            self.assertEqual(qc._queues, self.standard_solution)
            self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
            self.assertEqual(qc.mergeable_prs, [1, 4, 5, 7])
            self.assertEqual(qc.mergeable_queues, self.standard_solution)
        finally:
            gwfi.octopus_merge = git.octopus_merge
            gwfq.octopus_merge = git.octopus_merge

    def test_queueing_last_pr_build_not_started(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][gwfb.QueueIntegrationBranch].pop(0)
        solution['5.1'][gwfb.QueueIntegrationBranch].pop(0)
        solution['6.0'][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_queueing_last_pr_build_failed(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'pipeline': 'FAILED'}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][gwfb.QueueIntegrationBranch].pop(0)
        solution['5.1'][gwfb.QueueIntegrationBranch].pop(0)
        solution['6.0'][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_queueing_last_pr_other_key(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'other': 'SUCCESSFUL'}
        solution = deepcopy(self.standard_solution)
        solution['4.3'][gwfb.QueueIntegrationBranch].pop(0)
        solution['5.1'][gwfb.QueueIntegrationBranch].pop(0)
        solution['6.0'][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_queueing_fail_masked_by_success(self):
        problem = deepcopy(self.standard_problem)
        problem[1]['status'][0] = {'pipeline': 'FAILED'}
        problem[2]['status'][0] = {'pipeline': 'FAILED'}
        problem[3]['status'][1] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_queues, self.standard_solution)

    def test_queueing_all_failed(self):
        problem = deepcopy(self.standard_problem)
        for pr in problem.keys():
            for index_, _ in enumerate(problem[pr]['status']):
                problem[pr]['status'][index_] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [])
        self.assertEqual(qc.mergeable_queues, self.empty_solution)

    def test_queueing_all_inprogress(self):
        problem = deepcopy(self.standard_problem)
        for pr in problem.keys():
            for index_, _ in enumerate(problem[pr]['status']):
                problem[pr]['status'][index_] = {'pipeline': 'INPROGRESS'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [])
        self.assertEqual(qc.mergeable_queues, self.empty_solution)

    def test_queueing_mixed_fails(self):
        problem = deepcopy(self.standard_problem)
        problem[1]['status'][0] = {'pipeline': 'FAILED'}
        problem[2]['status'][0] = {'pipeline': 'FAILED'}
        problem[4]['status'][2] = {'pipeline': 'FAILED'}
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 4, 5, 7])
        self.assertEqual(qc.mergeable_prs, [])
        self.assertEqual(qc.mergeable_queues, self.empty_solution)

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
        self.assertEqual(qc.mergeable_prs, [])

    def test_queues_not_validated(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.QueuesNotValidated):
            qc.mergeable_prs == [1, 4, 5, 7]

    def assert_error_codes(self, excp, errors):
        msg = excp.exception.args[0]
        error_codes = set(re.findall('Q[0-9]*', msg))
        expected = set([error.code for error in errors])
        self.assertEqual(error_codes, expected)

    def test_validation_with_missing_master_queue(self):
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/5.1')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueMissing])

    def test_validation_updated_dev(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'development/4.3',
                           'file_pushed_without_bert-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueLateVsDev,
                                       exns.QueueInclusionIssue])

    def test_validation_no_integration_queues(self):
        self.submit_problem(self.standard_problem)
        branches = ['q/4.3', 'q/5.1', 'q/6.0']
        qc = self.feed_queue_collection(branches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueNotInSync])

    def test_validation_masterq_on_dev(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git reset --hard development/6.0')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueLateVsInt,
                                       exns.QueueInclusionIssue])

    def test_validation_masterq_late(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git reset --hard HEAD~')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueLateVsInt,
                                       exns.QueueInclusionIssue])

    def test_validation_masterq_younger(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'q/4.3',
                           'file_pushed_without_bert-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueYoungerThanInt])

    def test_validation_masterq_diverged(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/5.1')
        self.gitrepo.cmd('git reset --hard HEAD~')
        add_file_to_branch(self.gitrepo, 'q/5.1',
                           'file_pushed_without_bert-e.txt', do_push=False)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueDiverged,
                                       exns.QueueInclusionIssue])

    def test_validation_vertical_inclusion(self):
        qbranches = self.submit_problem(self.standard_problem)
        add_file_to_branch(self.gitrepo, 'q/7/5.1/improvement/bar2',
                           'file_pushed_without_bert-e.txt', do_push=True)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueLateVsInt,
                                       exns.QueueInclusionIssue])

    def test_validation_with_missing_first_intq(self):
        self.skipTest("skipping until completeness check is implemented")
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/1/4.3/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.QueueIncomplete])

    def test_validation_with_missing_middle_intq(self):
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/1/5.1/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp,
                                [exns.QueueInconsistentPullRequestsOrder])

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
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/4.3/bugfix/last')
                ]
            }),
            ('5.1', {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/5.1/bugfix/last'),
                    self.qint_branch('q/4/5.1/bugfix/foo'),
                    self.qint_branch('q/1/5.1/bugfix/bar')
                ]
            }),
            ('5.1.4', {
                gwfb.QueueBranch: self.queue_branch('q/5.1.4'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/4/5.1.4/bugfix/foo')
                ]
            }),
            ('6.0', {
                gwfb.QueueBranch: self.queue_branch('q/6.0'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/7/6.0/bugfix/last'),
                    self.qint_branch('q/4/6.0/bugfix/foo'),
                    self.qint_branch('q/3/6.0/feature/foo'),
                    self.qint_branch('q/1/6.0/bugfix/bar')
                ]
            }),
        ])
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, solution)
        self.assertEqual(qc.mergeable_prs, [1, 3, 4, 7])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_validation_with_failed_stabilization_branch(self):
        """A problem where two PRs are on two different merge paths."""
        problem = OrderedDict({
            1: {'dst': 'stabilization/5.1.4', 'src': 'bugfix/targeting_stab',
                'status': [{'pipeline': 'FAILED'},
                           {'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'SUCCESSFUL'}]},
            2: {'dst': 'development/4.3', 'src': 'bugfix/targeting_old',
                'status': [{'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'INPROGRESS'},
                           {'pipeline': None}]},
        })
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        queues = OrderedDict([
            ('4.3', {
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/4/4.3/bugfix/targeting_old'),
                ]
            }),
            ('5.1', {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/4/5.1/bugfix/targeting_old'),
                    self.qint_branch('q/1/5.1/bugfix/targeting_stab'),
                ]
            }),
            ('5.1.4', {
                gwfb.QueueBranch: self.queue_branch('q/5.1.4'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/1/5.1.4/bugfix/targeting_stab'),
                ]
            }),
            ('6.0', {
                gwfb.QueueBranch: self.queue_branch('q/6.0'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/4/6.0/bugfix/targeting_old'),
                    self.qint_branch('q/1/6.0/bugfix/targeting_stab'),
                ]
            }),
        ])
        self.assertEqual(qc._queues, queues)
        self.assertEqual(qc.mergeable_prs, [])
        solution = OrderedDict([
            ('4.3', {
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: []
            }),
            ('5.1', {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: []
            }),
            ('5.1.4', {
                gwfb.QueueBranch: self.queue_branch('q/5.1.4'),
                gwfb.QueueIntegrationBranch: []
            }),
            ('6.0', {
                gwfb.QueueBranch: self.queue_branch('q/6.0'),
                gwfb.QueueIntegrationBranch: []
            }),
        ])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_validation_with_failed_stabilization_branch_stacked(self):
        """A problem where a PR corrects a problem but is not mergeable yet.

        This is a corner case, where an additional PR (3) on stabilization
        branches fixes the first PR (1), but is not mergeable yet because
        another PR (2) blocks the way on another merge path.

        Currently waiving the fact that PR1 will be merged to avoid raising
        the complexity of the decision algorithm.

        """
        problem = OrderedDict({
            1: {'dst': 'stabilization/5.1.4', 'src': 'bugfix/targeting_stab',
                'status': [{'pipeline': 'FAILED'},
                           {'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'SUCCESSFUL'}]},
            2: {'dst': 'development/4.3', 'src': 'bugfix/targeting_old',
                'status': [{'pipeline': 'FAILED'},
                           {'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'SUCCESSFUL'}]},
            3: {'dst': 'stabilization/5.1.4', 'src': 'bugfix/targeting_stab2',
                'status': [{'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'SUCCESSFUL'},
                           {'pipeline': 'SUCCESSFUL'}]},
        })
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc.mergeable_prs, [1])

    def test_system_nominal_case(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # add a commit to w/5.1 branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/5.1/bugfix/TEST-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        self.gitrepo.cmd('git push origin')
        sha1_w_5_1 = self.gitrepo \
                         .cmd('git rev-parse w/5.1/bugfix/TEST-00001') \
                         .rstrip()

        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # get the new sha1 on w/6.0 (set_build_status_on_pr_id won't detect the
        # new commit in mocked mode)
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        sha1_w_6_0 = self.gitrepo \
                         .cmd('git rev-parse w/6.0/bugfix/TEST-00001') \
                         .rstrip()

        # check expected branches exist
        self.gitrepo.cmd('git fetch --prune')
        expected_branches = [
            'q/1/4.3/bugfix/TEST-00001',
            'q/1/5.1/bugfix/TEST-00001',
            'q/1/6.0/bugfix/TEST-00001',
            'w/5.1/bugfix/TEST-00001',
            'w/6.0/bugfix/TEST-00001'
        ]
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch))

        # set build status
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_5_1, state='SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_6_0, state='FAILED')
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)
        self.set_build_status(sha1=sha1_w_6_0, state='SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

        # check validity of repo and branches
        for branch in ['q/4.3', 'q/5.1', 'q/6.0']:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch))
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True))
        for dev in ['development/4.3', 'development/5.1', 'development/6.0']:
            branch = gwfb.branch_factory(self.gitrepo, dev)
            branch.checkout()
            self.gitrepo.cmd('git pull origin %s', dev)
            self.assertTrue(branch.includes_commit(pr.src_commit))
            if dev == 'development/4.3':
                self.assertFalse(branch.includes_commit(sha1_w_5_1))
            else:
                self.assertTrue(branch.includes_commit(sha1_w_5_1))
                self.gitrepo.cmd('cat abc')

        last_comment = pr.comments[-1].text
        self.assertIn('I have successfully merged', last_comment)

    def test_system_missing_integration_queue_before_in_queue(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/4.3')

        self.gitrepo.cmd('git push origin :q/1/5.1/bugfix/TEST-00001')

        with self.assertRaises(exns.QueueOutOfOrder):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.QueueOutOfOrder):
            self.handle(pr2.src_commit,
                        options=self.bypass_all,
                        backtrace=True)

        with self.assertRaises(exns.IncoherentQueues) as excp:
            self.handle(pr1.src_commit, options=self.bypass_all)
        self.assert_error_codes(excp, [
            exns.MasterQueueNotInSync,
            exns.QueueInconsistentPullRequestsOrder
        ])

    def test_reconstruction(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        # delete all q branches
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/4.3')
        dev.checkout()
        for qbranch in self.get_qbranches():
            branch = gwfb.branch_factory(self.gitrepo, qbranch)
            branch.checkout()  # get locally
            dev.checkout()  # move away
            branch.remove(do_push=True)

        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

    def test_decline_queued_pull_request(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5.1')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # declining main PR triggers cleanup of integration branches
        pr.decline()
        with self.assertRaises(exns.PullRequestDeclined):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # and yet it will merge upon successful builds on queues
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

    def test_lose_integration_branches_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5.1')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')

        # delete integration branch
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/6.0')
        intb = gwfb.branch_factory(self.gitrepo, 'w/6.0/bugfix/TEST-00001')
        intb.dst_branch = dev
        intb.checkout()
        intb.remove(do_push=True)

        # and yet it will merge
        with self.assertRaises(exns.Merged):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

    def set_build_status_on_branch_tip(self, branch_name, status):
        self.gitrepo.cmd('git fetch')
        branch = gwfb.branch_factory(self.gitrepo, branch_name)
        branch.checkout()
        sha1 = branch.get_latest_commit()
        self.set_build_status(sha1, status)
        return sha1

    def test_delete_all_integration_queues_of_one_pull_request(self):
        self.skipTest("skipping until completeness check is implemented")
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        # delete integration queues of pr1
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/6.0')
        intq1 = gwfb.branch_factory(
            self.gitrepo, 'q/1/6.0/bugfix/TEST-00001')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        sha1 = self.set_build_status_on_branch_tip(
            'q/3/6.0/bugfix/TEST-00002', 'SUCCESSFUL')

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(sha1, options=self.bypass_all, backtrace=True)

        # check the content of pr1 is not merged
        dev.checkout()
        self.gitrepo.cmd('git pull origin development/6.0')
        self.assertFalse(dev.includes_commit(pr1.src_commit))

    def test_delete_main_queues(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # delete main queue branch
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/6.0')
        intq1 = gwfb.branch_factory(self.gitrepo, 'q/6.0')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

    def test_feature_branch_augmented_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        old_sha1 = pr.src_commit

        # Add a new commit
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        sha1 = Branch(self.gitrepo, 'bugfix/TEST-00001').get_latest_commit()
        self.gitrepo.cmd('git push origin')

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status(old_sha1, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(old_sha1, options=self.bypass_all, backtrace=True)

        last_comment = pr.comments[-1].text
        self.assertIn('Partial merge', last_comment)
        self.assertIn(sha1, last_comment)

        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # check additional commit still here
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('cat abc')
        self.gitrepo.cmd('git checkout q/6.0')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('cat abc')

    def test_feature_branch_rewritten_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        old_sha1 = pr.src_commit

        # rewrite history of feature branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout bugfix/TEST-00001')
        self.gitrepo.cmd('git commit --amend -m "rewritten log"')
        self.gitrepo.cmd('git push -f origin')

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status(old_sha1, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(old_sha1, options=self.bypass_all, backtrace=True)

        last_comment = pr.comments[-1].text
        self.assertIn('Partial merge', last_comment)

        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_integration_branch_augmented_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5.1')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')

        # Add a new commit
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/6.0/bugfix/TEST-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        sha1 = Branch(self.gitrepo,
                      'w/6.0/bugfix/TEST-00001').get_latest_commit()
        self.gitrepo.cmd('git push origin')

        with self.assertRaises(exns.Merged):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        # Check the additional commit was not merged
        self.assertFalse(
            Branch(self.gitrepo, 'development/6.0').includes_commit(sha1))

    def test_integration_branches_dont_follow_dev(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        # create integration branches but don't queue yet
        self.handle(pr1.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # get the sha1's of integration branches
        self.gitrepo.cmd('git fetch')
        sha1s = dict()
        for version in ['5.1', '6.0']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/TEST-00001', version)
            self.gitrepo.cmd('git pull')
            sha1s[version] = self.gitrepo \
                .cmd('git rev-parse w/%s/bugfix/TEST-00001', version) \
                .rstrip()

        # merge some other work
        pr2 = self.create_pr('bugfix/TEST-00002', 'development/5.1')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)
        self.set_build_status_on_pr_id(pr2.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr2.id + 1, 'SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(
                pr2.src_commit, options=self.bypass_all, backtrace=True)

        # rerun on pr1, hope w branches don't get updated
        self.handle(pr1.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # verify
        self.gitrepo.cmd('git fetch')
        for version in ['5.1', '6.0']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/TEST-00001', version)
            self.gitrepo.cmd('git pull')
            self.assertEqual(
                sha1s[version],
                self.gitrepo
                    .cmd('git rev-parse w/%s/bugfix/TEST-00001', version)
                    .rstrip())

    def test_new_dev_branch_appears(self):
        pr = self.create_pr('bugfix/TEST-00001', 'stabilization/5.1.4')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')

        # introduce a new version, but not its queue branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/6.0')
        self.gitrepo.cmd('git checkout -b development/6.3')
        self.gitrepo.cmd('git push -u origin development/6.3')

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

    def test_dev_branch_decommissioned(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')

        # delete a middle dev branch
        self.gitrepo.cmd('git push origin :development/5.1')

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

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

        pr1 = self.create_pr('bugfix/TEST-00001', 'development/5.2')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr1.id + 1, 'SUCCESSFUL')

        # introduce a new stab, but not its queue branches
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/6.0')
        self.gitrepo.cmd('git checkout -b stabilization/5.2.0')
        self.gitrepo.cmd('git push -u origin stabilization/5.2.0')

        pr2 = self.create_pr('bugfix/TEST-00002', 'stabilization/5.2.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr1.id, pr2.id})

        with self.assertRaises(exns.Merged):
            self.handle(pr1.src_commit, options=self.bypass_all,
                        backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr2.id})

        self.set_build_status_on_branch_tip(
            'q/%d/5.2.0/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/5.2/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(pr2.src_commit, options=self.bypass_all,
                        backtrace=True)

        self.assertEqual(self.prs_in_queue(), set())

    def test_multi_branch_queues(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'stabilization/5.1.4')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        pr3 = self.create_pr('bugfix/TEST-00003', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr3.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr1.id, pr2.id, pr3.id})

        self.set_build_status_on_branch_tip(
            'q/%d/4.3/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00001' % pr1.id, 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1.4/bugfix/TEST-00002' % pr2.id, 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/4.3/bugfix/TEST-00003' % pr3.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1/bugfix/TEST-00003' % pr3.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00003' % pr3.id, 'SUCCESSFUL')
        with self.assertRaises(exns.NothingToDo):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr1.id, pr2.id, pr3.id})

        self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id, pr3.id})

        pr4 = self.create_pr('bugfix/TEST-00004', 'stabilization/5.1.4')
        with self.assertRaises(exns.Queued):
            self.handle(pr4.id, options=self.bypass_all, backtrace=True)
        with self.assertRaises(exns.NothingToDo):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id, pr3.id, pr4.id})

        self.set_build_status_on_branch_tip(
            'q/%d/5.1.4/bugfix/TEST-00004' % pr4.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1/bugfix/TEST-00004' % pr4.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00004' % pr4.id, 'FAILED')
        with self.assertRaises(exns.NothingToDo):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id, pr3.id, pr4.id})

        pr5 = self.create_pr('bugfix/TEST-00005', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr5.id, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id, pr3.id, pr4.id, pr5.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00005' % pr5.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), set())

    def test_multi_branch_queues_2(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/6.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr1.id, pr2.id})

        self.set_build_status_on_branch_tip(
            'q/%d/4.3/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/5.1/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/%d/6.0/bugfix/TEST-00002' % pr2.id, 'FAILED')
        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id})

    def test_queue_conflict(self):
        pr1 = self.create_pr('bugfix/TEST-0006', 'development/6.0',
                             file_='toto.txt')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-0006-other', 'development/6.0',
                             file_='toto.txt')
        with self.assertRaises(exns.QueueConflict):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

    def test_nothing_to_do_unknown_sha1(self):
        sha1 = "f" * 40
        with self.assertRaises(exns.NothingToDo):
            self.handle(sha1, options=self.bypass_all, backtrace=True)


class TaskQueueTests(RepositoryTests):
    def init_berte(self, options=[], backtrace=True, **all_settings):
        data = DEFAULT_SETTINGS.format(
            admin=self.args.admin_username,
            robot=self.args.robot_username,
            owner=self.args.owner,
            slug='%s_%s' % (self.args.repo_prefix, self.args.admin_username),
            host=self.args.git_host
        )
        with open('test_settings.yml', 'w') as settings_file:
            settings_file.write(data)
        settings = setup_settings('test_settings.yml')
        settings['robot_password'] = self.args.robot_password
        settings['jira_password'] = 'dummy_jira_password'
        settings['cmd_line_options'] = options
        settings['backtrace'] = backtrace
        settings['sentry_dsn'] = self.args.sentry_dsn
        settings.update(all_settings)
        self.berte = BertE(settings)

    def process_job(self, job, status=None):
        self.berte.put_job(job)
        self.berte.process_task()
        self.assertTrue(job.done)
        if status is not None:
            self.assertEqual(job.status, status)
        return job

    def make_pr_job(self, pr, **settings):
        client = pr.client
        pr.client = self.berte.client
        job = PullRequestJob(
            bert_e=self.berte, pull_request=deepcopy(pr),
            url=self.berte.settings.pull_request_base_url.format(pr_id=pr.id),
            settings=settings
        )
        pr.client = client
        return job

    def process_pr_job(self, pr, status=None, **settings):
        job = self.make_pr_job(pr, **settings)
        return self.process_job(job, status)

    def process_bitbucket_pr_job_with_429(self, pr, status=None, **settings):
        with requests_mock.Mocker(real_http=True) as m:
            m.register_uri('POST',
                           'https://api.bitbucket.org/1.0/repositories/'
                           '{owner}/{slug}/pullrequests/1/comments'.format(
                               owner=self.args.owner,
                               slug=('%s_%s' % (self.args.repo_prefix,
                                                self.args.admin_username))),
                           additional_matcher=dynamic_filtering,
                           status_code=429)
            return self.process_pr_job(pr, status, **settings)

    def make_sha1_job(self, sha1, **settings):
        job = CommitJob(
            bert_e=self.berte, commit=sha1,
            url=self.berte.settings.commit_base_url.format(commit_id=sha1),
            settings=settings
        )
        return job

    def process_sha1_job(self, sha1, status=None, **settings):
        job = self.make_sha1_job(sha1, **settings)
        return self.process_job(job, status)

    def test_berte_duplicate_pr_job(self):
        self.init_berte()
        pr = self.create_pr('bugfix/TEST-0001', 'development/6.0')
        for _ in range(5):
            self.berte.put_job(self.make_pr_job(pr))

        self.assertEqual(len(self.berte.task_queue.queue), 1)

    def test_berte_duplicate_sha1_job(self):
        self.init_berte()
        sha1 = '0badf00ddeadbeef'
        for _ in range(5):
            self.berte.put_job(self.make_sha1_job(sha1))

        self.assertEqual(len(self.berte.task_queue.queue), 1)

    def test_berte_worker_job_never_crashes(self):
        self.init_berte()
        pr = self.create_pr('bugfix/TEST-0001', 'development/6.0')
        self.berte.put_job(self.make_pr_job(pr))
        real_process = BertE.process

        def fake_process(self, job):
            raise Exception("Something went wrong!!!")

        try:
            BertE.process = fake_process
            self.berte.process_task()
        except Exception:
            self.fail("BertE.process_task should never fail")
        finally:
            BertE.process = real_process

    def test_status_no_queue(self):
        self.init_berte(options=self.bypass_all, disable_queues=True)
        pr_titles = ['bugfix/TEST-1', 'bugfix/TEST-2', 'bugfix/TEST-3']
        prs = [self.create_pr(title, 'development/4.3') for title in pr_titles]
        jobs = [self.process_pr_job(pr, 'SuccessMessage') for pr in prs]

        merged_prs = self.berte.status.get('merged PRs', [])
        self.assertEquals(len(merged_prs), 3)
        for merged, job in zip(merged_prs, jobs):
            self.assertEqual(merged['id'], job.pull_request.id)
            self.assertTrue(
                job.start_time < merged['merge_time'] < job.end_time)

    def test_status_with_queue(self):
        self.init_berte(options=self.bypass_all)
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.process_pr_job(pr, 'Queued')

        # check expected branches exist
        self.gitrepo.cmd('git fetch --prune')
        expected_branches = [
            'q/1/4.3/bugfix/TEST-00001',
            'q/1/5.1/bugfix/TEST-00001',
            'q/1/6.0/bugfix/TEST-00001',
            'w/5.1/bugfix/TEST-00001',
            'w/6.0/bugfix/TEST-00001'
        ]
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        sha1_q_6_0 = self.gitrepo._remote_branches['q/6.0']

        self.process_sha1_job(sha1_q_6_0, 'NothingToDo')

        status = self.berte.status.get('merge queue', OrderedDict())
        self.assertIn(1, status)
        self.assertEqual(len(status[1]), 3)
        versions = tuple(version for version, _ in status[1])
        self.assertEqual(versions, ('6.0', '5.1', '4.3'))
        for _, sha1 in status[1]:
            self.set_build_status(sha1=sha1, state='SUCCESSFUL')
        self.process_sha1_job(sha1_q_6_0, 'Merged')

        merged_pr = self.berte.status.get('merged PRs', [])
        self.assertEqual(len(merged_pr), 1)
        self.assertEqual(merged_pr[0]['id'], 1)

    def test_status_with_queue_without_octopus(self):
        # monkey patch to skip octopus merge in favor of regular 2-way merges
        gwfi.octopus_merge = git.consecutive_merge
        gwfq.octopus_merge = git.consecutive_merge

        try:
            self.init_berte(options=self.bypass_all)
            pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
            self.process_pr_job(pr, 'Queued')

            # check expected branches exist
            self.gitrepo.cmd('git fetch --prune')
            expected_branches = [
                'q/1/4.3/bugfix/TEST-00001',
                'q/1/5.1/bugfix/TEST-00001',
                'q/1/6.0/bugfix/TEST-00001',
                'w/5.1/bugfix/TEST-00001',
                'w/6.0/bugfix/TEST-00001'
            ]
            for branch in expected_branches:
                self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                                'branch %s not found' % branch)

            sha1_q_6_0 = self.gitrepo._remote_branches['q/6.0']

            self.process_sha1_job(sha1_q_6_0, 'NothingToDo')

            status = self.berte.status.get('merge queue', OrderedDict())
            versions = tuple(version for version, _ in status[1])
            for _, sha1 in status[1]:
                self.set_build_status(sha1=sha1, state='SUCCESSFUL')
            self.assertEqual(versions, ('6.0', '5.1', '4.3'))
            self.process_sha1_job(sha1_q_6_0, 'Merged')

            merged_pr = self.berte.status.get('merged PRs', [])
            self.assertEqual(len(merged_pr), 1)
            self.assertEqual(merged_pr[0]['id'], 1)
        finally:
            gwfi.octopus_merge = git.octopus_merge
            gwfq.octopus_merge = git.octopus_merge

    def test_job_evaluate_pull_request(self):
        self.init_berte(options=self.bypass_all)

        # test behaviour when PR does not exist
        self.process_job(
            EvalPullRequestJob(1, bert_e=self.berte),
            'PullRequestNotFound'
        )

        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.process_job(
            EvalPullRequestJob(pr.id, bert_e=self.berte),
            'Queued'
        )

    def test_job_rebuild_queues(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            RebuildQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'NothingToDo'
        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'NothingToDo')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/4.3')
            for n in range(1, 4)
        ]

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'q/4.3',
            'q/5.1',
            'q/6.0',
            'q/1/4.3/feature/TEST-01',
            'q/1/5.1/feature/TEST-01',
            'q/1/6.0/feature/TEST-01',
            'q/2/4.3/feature/TEST-02',
            'q/2/5.1/feature/TEST-02',
            'q/2/6.0/feature/TEST-02',
            'q/3/4.3/feature/TEST-03',
            'q/3/5.1/feature/TEST-03',
            'q/3/6.0/feature/TEST-03',
        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # Put a 'wait' command on one of the PRs to exclude it from the queue
        excluded, *requeued = prs
        excluded.add_comment("@%s wait" % self.args.robot_username)

        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'QueuesDeleted')

        # Check that the queues are destroyed
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True),
                             'branch %s still exists' % branch)

        # Check that the robot is going to be waken up on all of the previously
        # queued prs.
        self.assertEqual(len(self.berte.task_queue.queue), len(prs))

        while not self.berte.task_queue.empty():
            self.berte.process_task()

        expected_branches = [
            'q/4.3',
            'q/5.1',
            'q/6.0',
            'q/2/4.3/feature/TEST-02',
            'q/2/5.1/feature/TEST-02',
            'q/2/6.0/feature/TEST-02',
            'q/3/4.3/feature/TEST-03',
            'q/3/5.1/feature/TEST-03',
            'q/3/6.0/feature/TEST-03',
        ]

        excluded_branches = [
            'q/1/4.3/feature/TEST-01',
            'q/1/5.1/feature/TEST-01',
            'q/1/6.0/feature/TEST-01',
        ]

        # Check that all 'requeued' PRs are queued again
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch, True),
                            'branch %s not found' % branch)

        # Check that the excluded PR is *not* queued.
        for branch in excluded_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch),
                             "branch %s shouldn't exist" % branch)

    def test_bypass_prefixes(self):
        self.init_berte()
        pr = self.create_pr('documentation/stuff', 'development/4.3')

        # No configured bypass_prefixes
        self.process_pr_job(pr, 'MissingJiraId')
        # bypass_prefixes configured but doesn't contain 'documentation'
        self.process_pr_job(pr, 'MissingJiraId', bypass_prefixes=['settings'])

        # bypass_prefixes is configured and contains 'documentation'
        # Jira checks should be auto-bypassed
        self.process_pr_job(pr, 'ApprovalRequired',
                            bypass_prefixes=['documentation'])

    def test_sentry(self):
        """Test Sentry support by throwing an exception which will be
        sent to Sentry eventually.
        """
        self.init_berte()
        self.process_job(self.process_job(FaultJob(self.berte), "FaultError"))

    def test_flakiness(self):
        if self.args.git_host != 'bitbucket':
            self.skipTest("flakiness test is only supported on bitbucket")
        self.init_berte()
        pr = self.create_pr('bugfix/TEST-00429', 'development/4.3')
        self.process_bitbucket_pr_job_with_429(pr)
        last_comment = pr.get_comments()[-1].text
        self.assertTrue(FLAKINESS_MESSAGE_TITLE in last_comment)


def main():
    parser = argparse.ArgumentParser(description='Launches Bert-E tests.')
    parser.add_argument(
        'owner',
        help='Owner of test repository (aka Bitbucket/GitHub team)')
    parser.add_argument('robot_username',
                        help='Robot Bitbucket/GitHub username')
    parser.add_argument('robot_password',
                        help='Robot Bitbucket/GitHub password')
    parser.add_argument('contributor_username',
                        help='Contributor Bitbucket/GitHub username')
    parser.add_argument('contributor_password',
                        help='Contributor Bitbucket/GitHub password')
    parser.add_argument('admin_username',
                        help='Privileged user Bitbucket/GitHub username')
    parser.add_argument('admin_password',
                        help='Privileged user Bitbucket/GitHub password')
    parser.add_argument('tests', nargs='*', help='run only these tests')
    parser.add_argument('--sentry-dsn', dest='sentry_dsn',
                        help='url to the sentry dsn if needed',
                        default='')
    parser.add_argument('--repo-prefix', default="_test_bert_e",
                        help='Prefix of the test repository')
    parser.add_argument('-v', action='store_true', dest='verbose',
                        help='Verbose mode')
    parser.add_argument('--failfast', action='store_true', default=False,
                        help='Return on first failure')
    parser.add_argument('--git-host', default='mock',
                        help='Choose the git host to run tests (slower tests)')
    parser.add_argument('--disable-queues', action='store_true', default=False,
                        help='deactivate queue feature during tests')
    RepositoryTests.args = parser.parse_args()

    if (RepositoryTests.args.admin_username ==
            RepositoryTests.args.robot_username):
        sys.exit('Cannot use the same login for robot and superuser, '
                 'please specify another login.')

    if (RepositoryTests.args.admin_username ==
            RepositoryTests.args.contributor_username):
        sys.exit('Cannot use the same login for superuser and user, '
                 'please specify another login.')

    if (RepositoryTests.args.robot_username ==
            RepositoryTests.args.contributor_username):
        sys.exit('Cannot use the same login for normal user and robot, '
                 'please specify another login.')

    if RepositoryTests.args.git_host == 'mock':
        bitbucket_api.Client = bitbucket_api_mock.Client
        bitbucket_api.Repository = bitbucket_api_mock.Repository
        bitbucket_api.Task = bitbucket_api_mock.Task
    jira_api.JiraIssue = jira_api_mock.JiraIssue

    if RepositoryTests.args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        # it is expected that Bert-E issues some warning
        # during the tests, only report critical stuff
        logging.basicConfig(level=logging.CRITICAL)

    sys.argv = [sys.argv[0]]
    sys.argv.extend(RepositoryTests.args.tests)
    loader = unittest.TestLoader()
    loader.testMethodPrefix = "test_"
    unittest.main(failfast=RepositoryTests.args.failfast, testLoader=loader)


if __name__ == '__main__':
    main()
