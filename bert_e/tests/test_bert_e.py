# Copyright 2016-2018 Scality
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
import os.path
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
from os import getenv

import requests
import requests_mock

from bert_e import exceptions as exns
from bert_e.bert_e import main as bert_e_main
from bert_e.bert_e import BertE
from bert_e.jobs.create_branch import CreateBranchJob
from bert_e.jobs.delete_branch import DeleteBranchJob
from bert_e.jobs.delete_queues import DeleteQueuesJob
from bert_e.jobs.eval_pull_request import EvalPullRequestJob
from bert_e.jobs.force_merge_queues import ForceMergeQueuesJob
from bert_e.jobs.rebuild_queues import RebuildQueuesJob
from bert_e.git_host import bitbucket as bitbucket_api
from bert_e.git_host import mock as bitbucket_api_mock
from bert_e.git_host.base import BertESession
from bert_e.git_host.base import NoSuchRepository
from bert_e.git_host.factory import client_factory
from bert_e.job import CommitJob, PullRequestJob
from bert_e.lib import jira as jira_api
from bert_e.lib.git import Repository as GitRepository
from bert_e.lib.git import Branch, MergeFailedException
from bert_e.lib.retry import RetryHandler
from bert_e.lib.simplecmd import CommandError, cmd
from bert_e.settings import setup_settings
from bert_e.workflow import gitwaterflow as gwf
from bert_e.workflow import git_utils
from bert_e.workflow.gitwaterflow import branches as gwfb
from bert_e.workflow.gitwaterflow import integration as gwfi
from bert_e.workflow.gitwaterflow import queueing as gwfq

from .mocks import jira as jira_api_mock


FLAKINESS_MESSAGE_TITLE = 'Temporary bitbucket failure'  # noqa


DEFAULT_SETTINGS = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
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
jira_email: dummy@mail.com
jira_keys:
  - TEST
admins:
  - {admin}
project_leaders:
  - {admin}
""" # noqa


log = logging.getLogger(__name__)


def initialize_git_repo(repo, username, usermail):
    """resets the git repo"""
    assert '/ring/' not in repo._url  # This is a security, do not remove
    repo.cmd('git init --initial-branch=master')
    repo.cmd('git config user.email %s' % usermail)
    repo.cmd('git config user.name %s' % username)
    repo.cmd('touch a')
    repo.cmd('git add a')
    repo.cmd('git commit -m "Initial commit"')
    repo.cmd('git remote add origin ' + repo._url)
    for major, minor, micro in [(4, 3, 18), (5, 1, 4), (10, 0, 1)]:
        major_minor = "%s.%s" % (major, minor)
        major_minor_micro = "%s.%s.%s" % (major, minor, micro)
        create_branch(repo, 'release/' + major_minor, do_push=False)
        if major != 10:
            create_branch(repo, 'hotfix/%s.%s.%s' %
                          (major, minor - 1, micro),
                          do_push=False)
            create_branch(repo, 'hotfix/%s.%s.%s' %
                          (major, minor - 1, micro - 1),
                          do_push=False)
            create_branch(repo, 'hotfix/%s.%s.%s' %
                          (major, minor - 1, micro - 2),
                          do_push=False)
        else:
            create_branch(repo, 'hotfix/10.0.0', do_push=False)
        create_branch(repo, f'development/{major}.{minor}.{micro}',
                      file_=True, do_push=False)
        create_branch(repo, 'development/' + major_minor,
                      f'development/{major_minor_micro}',
                      file_=True, do_push=False)
        create_branch(repo, f'development/{major}',
                      f'development/{major_minor}',
                      file_=True, do_push=False)

        if major != 6 and major != 10:
            repo.cmd('git tag %s.%s.%s', major, minor, micro - 1)

        if major == 4:
            repo.cmd('git tag %s.%s.%s', major, minor - 1, micro - 1)

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


def add_file_to_branch(repo, branch_name, file_name, do_push=True, folder='.'):
    if file_name is True:
        file_name = 'file_created_on_' + branch_name.replace('/', '_')

    file_path = os.path.dirname(os.path.abspath(__file__))

    repo.cmd(f'git checkout {branch_name}')
    repo.cmd(f'mkdir -p {folder}')
    if os.path.isfile(f'{file_path}/assets/{file_name}'):
        repo.cmd(f'cp {file_path}/assets/{file_name} {folder}/{file_name}')
    else:
        repo.cmd(f'echo {branch_name} >  {file_name}')
    repo.cmd(f'git add {folder}/{file_name}')
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

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('epic')

        with self.assertRaises(exns.BranchNameInvalid):
            self.feature_branch('epic/')

        # valid names
        self.feature_branch('feature/TEST-0005')
        self.feature_branch('improvement/TEST-1234')
        self.feature_branch('bugfix/TEST-1234')
        self.feature_branch('epic/TEST-1234')

        src = self.feature_branch('project/TEST-0005')
        self.assertEqual(src.jira_issue_key, 'TEST-0005')
        self.assertEqual(src.jira_project, 'TEST')

        # fix accidental lowercasing of JIRA project keys
        src = self.feature_branch('project/test-0006')
        self.assertEqual(src.jira_issue_key, 'TEST-0006')
        self.assertEqual(src.jira_project, 'TEST')

        src = self.feature_branch('feature/PROJECT-05-some-text_here')
        self.assertEqual(src.jira_issue_key, 'PROJECT-05')
        self.assertEqual(src.jira_project, 'PROJECT')

        src = self.feature_branch('feature/some-text_here')
        self.assertIsNone(src.jira_issue_key)
        self.assertIsNone(src.jira_project)

        src = self.feature_branch('dependabot/npm_and_yarn/ui/lodash-4.17.13')
        self.assertIsNone(src.jira_issue_key)
        self.assertIsNone(src.jira_project)

    def test_destination_branch_names(self):

        with self.assertRaises(exns.BranchNameInvalid):
            gwfb.DevelopmentBranch(repo=None, name='feature-TEST-0005')

        # valid names
        gwfb.DevelopmentBranch(repo=None, name='development/4.3')
        gwfb.DevelopmentBranch(repo=None, name='development/5.1')
        gwfb.DevelopmentBranch(repo=None, name='development/10.0')
        gwfb.HotfixBranch(repo=None, name='hotfix/6.6.6')

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
        # remove expected_ignored branches that would not be added by cascade
        # add_branch() property
        i = 0
        while i < len(expected_ignored):
            if expected_ignored[i].startswith('hotfix/'):
                if destination is None or \
                   destination != expected_ignored[i]:
                    expected_ignored.pop(i)
                    continue
            i = i + 1
        expected_ignored.sort()

        my_dst = None
        if destination is not None:
            my_dst = gwfb.branch_factory(FakeGitRepo(), destination)

        for branch in all_branches:
            c.add_branch(branch, my_dst)

        for tag in tags:
            c.update_versions(tag)

        c._update_major_versions()

        # check merge_paths now (finalize not required)
        if merge_paths:
            paths = c.get_merge_paths()
            self.assertEqual(len(merge_paths), len(paths))
            for exp_path, path in zip(merge_paths, paths):
                self.assertEqual(len(exp_path), len(path))
                for exp_branch, branch in zip(exp_path, path):
                    self.assertEqual(exp_branch, branch.name)

        c.finalize(gwfb.branch_factory(FakeGitRepo(), destination))

        # set hfrev in hotfix branches present in expected_dest list
        for i in range(len(expected_dest)):
            if expected_dest[i].name.startswith('hotfix/'):
                for c_branch in c.dst_branches:
                    if c_branch.name == expected_dest[i].name:
                        expected_dest[i].hfrev = c_branch.hfrev
                        break

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

    def test_branch_cascade_target_first_dev(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': False},
            2: {'name': 'development/5.1', 'ignore': False},
            3: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '5.1.3']
        fixver = ['4.3.18', '5.1.4', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_middle_dev(self):
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': True},
            2: {'name': 'development/5.1', 'ignore': False},
            3: {'name': 'development/10.0', 'ignore': False},
        })
        tags = ['4.3.16', '4.3.17', '5.1.3']
        fixver = ['5.1.4', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_last_dev(self):
        destination = 'development/10.0'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': True},
            2: {'name': 'development/5.1', 'ignore': True},
            3: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', '5.1.3']
        fixver = ['10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_hotfix(self):
        destination = 'hotfix/6.6.6'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': True},
            2: {'name': 'development/5.1', 'ignore': True},
            3: {'name': 'hotfix/6.6.5', 'ignore': True},
            4: {'name': 'hotfix/6.6.6', 'ignore': False},
            5: {'name': 'hotfix/6.6.7', 'ignore': True},
            6: {'name': 'development/6.6', 'ignore': True},
            7: {'name': 'hotfix/10.0.3', 'ignore': True},
            8: {'name': 'hotfix/10.0.4', 'ignore': True},
            9: {'name': 'development/10.0', 'ignore': True}
        })
        tags = ['4.3.16', '4.3.17', '5.1.3', '6.6.6', '10.0.3.1']
        fixver = ['6.6.6.1']
        self.finalize_cascade(branches, tags, destination, fixver)
        tags = ['4.3.16', '4.3.17', '4.3.18_rc1', '5.1.3', '5.1.4_rc1',
                '6.6.6.0', '10.0.3.1']
        fixver = ['6.6.6.1']
        self.finalize_cascade(branches, tags, destination, fixver)
        tags = ['4.3.16', '4.3.17', '5.1.3', '6.6.6.1', '10.0.3.1']
        fixver = ['6.6.6.2']
        self.finalize_cascade(branches, tags, destination, fixver)
        tags = ['4.3.16', '4.3.17', '5.1.3', '6.6.6.1', '6.6.6.2', '10.0.3.1']
        fixver = ['6.6.6.3']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_target_three_digit_dev(self):
        """Test cascade targeting three-digit development branch"""
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17', 'ignore': False},
            2: {'name': 'development/4.3', 'ignore': False},
            3: {'name': 'development/5.1', 'ignore': False},
            4: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.14', '4.3.16', '5.1.3']
        fixver = ['4.3.17', '4.3.18', '5.1.4', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_with_two_three_digit_dev(self):
        """Test cascade targeting three-digit development branch"""
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.15', 'ignore': True},
            2: {'name': 'development/4.3.17', 'ignore': False},
            3: {'name': 'development/4.3', 'ignore': False},
            4: {'name': 'development/5.1.1', 'ignore': False},
            5: {'name': 'development/5.1', 'ignore': False},
            6: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.14', '4.3.16', '5.1.3']
        fixver = ['4.3.17', '4.3.18', '5.1.1', '5.1.4', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_four_digit_fix_version(self):
        """Test handling dev/x.y.z with existing x.y.z tag"""
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17', 'ignore': False},
            2: {'name': 'development/4.3', 'ignore': False},
            3: {'name': 'development/5.1.8', 'ignore': False},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.17.0', '4.3.18', '5.1.3', '5.1.7']
        fixver = ['4.3.17', '4.3.19', '5.1.8', '5.1.9', '10.0.0']
        with self.assertRaises(exns.ReleaseAlreadyExists):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_with_three_digit_dev_and_hf(self):
        """Test cascade targeting three-digit development branch"""
        destination = 'development/4.3.17'
        branches = OrderedDict({
            1: {'name': 'development/4.3.15', 'ignore': True},
            2: {'name': 'development/4.3.17', 'ignore': False},
            3: {'name': 'development/4.3', 'ignore': False},
            4: {'name': 'development/5.1.1', 'ignore': False},
            5: {'name': 'hotfix/5.1.3', 'ignore': True},
            6: {'name': 'development/5.1', 'ignore': False},
            7: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.14', '4.3.16', '5.1.3.1', '5.1.5']
        fixver = ['4.3.17', '4.3.18', '5.1.1', '5.1.6', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_hotfix_and_development_three_digit(self):
        destination = 'hotfix/4.3.18'
        branches = OrderedDict({
            1: {'name': 'development/4.3.18', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            5: {'name': 'hotfix/4.3.18', 'ignore': False},
        })
        tags = ['4.3.16', '4.3.17', '4.3.18']
        fixver = ['4.3.18.1']
        with self.assertRaises(exns.ReleaseAlreadyExists):
            self.finalize_cascade(branches, tags, destination, fixver)

        destination = 'development/4.3.18'
        branches = OrderedDict({
            1: {'name': 'development/4.3.18', 'ignore': False},
            2: {'name': 'development/4.3', 'ignore': False},
            5: {'name': 'hotfix/4.3.18', 'ignore': True},
        })
        tags = ['4.3.16', '4.3.17', '4.3.18']
        fixver = ['4.3.18']
        with self.assertRaises(exns.ReleaseAlreadyExists):
            self.finalize_cascade(branches, tags, destination, fixver)

        destination = 'hotfix/4.3.18'
        branches = OrderedDict({
            1: {'name': 'development/4.3.19', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            5: {'name': 'hotfix/4.3.18', 'ignore': False},
        })
        tags = ['4.3.18']
        fixver = ['4.3.18.1']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_mixed_versions_0(self):
        """Test cascade with mix of 2-digit and 3-digit development branches"""
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            3: {'name': 'development/5.1.0', 'ignore': True},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/10', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.18']
        fixver = ['5.1.1', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_mixed_versions(self):
        """Test cascade with mix of 2-digit and 3-digit development branches"""
        destination = 'development/5.1'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17', 'ignore': True},
            2: {'name': 'development/4.3', 'ignore': True},
            3: {'name': 'development/5.1.8', 'ignore': True},
            4: {'name': 'development/5.1', 'ignore': False},
            5: {'name': 'development/10.0', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.18', '5.1.3', '5.1.7']
        fixver = ['5.1.9', '10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_branch_cascade_invalid_dev_branch(self):
        destination = 'development/4.3.17.1'
        branches = OrderedDict({
            1: {'name': 'development/4.3.17.1', 'ignore': False}
        })
        tags = []
        fixver = []
        with self.assertRaises(exns.UnrecognizedBranchPattern):
            self.finalize_cascade(branches, tags, destination, fixver)

    def test_tags_without_stabilization(self):
        destination = 'development/10.0'
        branches = OrderedDict({
            1: {'name': 'development/5.1', 'ignore': True},
            2: {'name': 'development/10.0', 'ignore': False}
        })
        merge_paths = [
            ['development/5.1', 'development/10.0']
        ]

        tags = []
        fixver = ['10.0.0']
        self.finalize_cascade(branches, tags, destination,
                              fixver, merge_paths)

        tags = ['toto']
        fixver = ['10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['toto', '10.0.2']
        fixver = ['10.0.3']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['10.0.15_rc1']
        fixver = ['10.0.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['10.0.15_rc1', '4.2.1', '10.0.0']
        fixver = ['10.0.1']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['10.0.15_rc1', '10.0.0', '5.1.4', '10.0.1']
        fixver = ['10.0.2']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['10.0.4000']
        fixver = ['10.0.4001']
        self.finalize_cascade(branches, tags, destination, fixver)

        tags = ['10.0.4000', '10.0.3999']
        fixver = ['10.0.4001']
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_with_v_prefix(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': False},
            2: {'name': 'development/5.1', 'ignore': False},
            3: {'name': 'development/10.0', 'ignore': False}
        })
        # mix and match tags with v prefix and without
        tags = ['4.3.16', '4.3.17', 'v5.1.3', 'v10.0.1']
        fixver = ['4.3.18', '5.1.4', '10.0.2']
        self.finalize_cascade(branches, tags, destination, fixver)
        # only tags with v prefix
        v_tags = ['v4.3.16', 'v4.3.17', 'v5.1.3', 'v10.0.1']
        # expect the same result
        self.finalize_cascade(branches, v_tags, destination, fixver)

    def test_major_development_branch(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': False},
            2: {'name': 'development/4', 'ignore': False},
            3: {'name': 'development/5.1', 'ignore': False},
            4: {'name': 'development/10.0', 'ignore': False},
            5: {'name': 'development/10', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', 'v5.1.3', 'v10.0.1']
        fixver = []
        with self.assertRaises(AssertionError):
            self.finalize_cascade(branches, tags, destination, fixver)
        fixver = ['4.3.18', '4.4.0', '5.1.4', '10.0.2', '10.1.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        destination = 'development/4'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': True},
            2: {'name': 'development/4', 'ignore': False}
        })
        fixver = ['4.4.0']
        self.finalize_cascade(branches, tags, destination, fixver)

        branches = OrderedDict({
            1: {'name': 'development/4', 'ignore': False}
        })
        self.finalize_cascade(branches, tags, destination, fixver)

    def test_major_development_branch_no_tag_bump(self):
        destination = 'development/4.3'
        branches = OrderedDict({
            1: {'name': 'development/4.3', 'ignore': False},
            2: {'name': 'development/4', 'ignore': False},
            3: {'name': 'development/5.1', 'ignore': False},
            4: {'name': 'development/10.0', 'ignore': False},
            5: {'name': 'development/10', 'ignore': False}
        })
        tags = ['4.3.16', '4.3.17', 'v5.1.3']
        fixver = ['4.3.18', '4.4.0', '5.1.4', '10.0.0', '10.1.0']
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
        branch = gwfb.IntegrationBranch(FakeGitRepo(), 'w/5.0/feature/TEST-01')

        build_fail = exns.BuildFailed(
            branch=branch,
            build_url=build_url,
            commit_url=commit_url,
            githost="github",
            active_options=None,
            owner="owner",
            slug="slug",
        )
        self.assertIn('The [build]({}) for [commit]({})'
                      ' did not succeed'.format(build_url, commit_url),
                      build_fail.msg)

    def test_build_fail_with_url_to_none(self):
        branch = gwfb.IntegrationBranch(FakeGitRepo(), 'w/5.0/feature/TEST-01')
        build_fail = exns.BuildFailed(
            branch=branch,
            build_url=None,
            githost="mock",
            commit_url=None,
            active_options=None
        )
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
        self.ci: bool = bool(getenv('CI', False))
        if self.ci:
            # print a group with the test name that is about to run
            log.info(f"\n::group::{self.__class__}.{self._testMethodName}")
        self.admin_id = None
        self.contributor_id = None
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
        if self.args.git_host == 'bitbucket':
            self.contributor_id = self.contributor_bb.client.get_user_id()
            self.admin_id = self.admin_bb.client.get_user_id()

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
        if self.ci:
            # end the group with the test name that just ran
            log.info("\n::endgroup::")

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
        sys.argv.append('dummy_jira_token')
        sys.argv.append(str(token))
        try:
            bert_e_main()
        except exns.Queued as excp:
            queued_excp = excp
        except exns.SilentException:
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
                id = int(re.findall(r'\d+', pr.description)[0])
                pr = self.robot_bb.get_pull_request(pull_request_id=id)
            sha1 = pr.src_commit

        except ValueError:
            # token is a sha1, use it to filter on content
            sha1 = token
        command = 'git branch -r --contains %s --list origin/q/w/[0-9]*/*'
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
        sys.argv.append('dummy_jira_token')
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
        admin = self.args.admin_username
        contributor = self.args.contributor_username
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
        if self.args.git_host == 'bitbucket':
            admin = '%s@%s' % (self.args.admin_username, self.admin_id)
            contributor = '%s@%s' % (self.args.contributor_username,
                                     self.contributor_id)
        data = settings.format(
            admin=admin,
            contributor=contributor,
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
        sys.argv.append('dummy_jira_token')
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
        for version in ['5.1', '10.0']:
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

    def test_full_merge_manual_for_hotfix(self):
        """Test the following conditions:

        - Author approval required,
        - can merge successfully by bypassing all checks,
        - cannot merge a second time.

        """
        pr = self.create_pr('bugfix/TEST-0001', 'hotfix/4.2.17')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # check backtrace mode on the same error, and check same error happens
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        # check success mode
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # check integration branches have been removed
        for version in ['4.3', '5.1', '10.0']:
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
robot: {robot}
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
        pr = self.create_pr('feature/TEST-0002', 'development/5')
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
        self.admin_bb.get_pull_request(pull_request_id=pr.id + 3)
        # Only three integration PRs should have been created
        with self.assertRaises(Exception):
            self.admin_bb.get_pull_request(pull_request_id=pr.id + 4)

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
robot: {robot}
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
        pr = self.create_pr('feature/TEST-0042', 'development/10')
        self.handle(pr.id, settings=settings, options=options)
        self.assertIs(len(list(pr.get_comments())), 1)
        self.assertIn('Hello %s' % self.args.contributor_username,
                      self.get_last_pr_comment(pr))

    def test_request_integration_branch_creation(self):
        """Test comments to request integration branches creation.

        1. Create a PR and ensure the proper message is sent regarding
           the creation of integration branches.
        2. Request the creation of integration branches and ensure the
           branches are created.
        3. Once the integration branches are created,
           ensure the bot is able to merge the PR.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_branches: false
always_create_integration_pull_requests: false
admins:
  - {admin}
""" # noqa
        options = self.bypass_all_but(['bypass_build_status'])
        pr = self.create_pr('feature/TEST-0069', 'development/4.3')
        with self.assertRaises(exns.RequestIntegrationBranches):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)
        self.assertEqual(len(list(pr.get_comments())), 2)
        self.assertIn(
            'Request integration branches', self.get_last_pr_comment(pr))
        self.assertIn(
            '/create_integration_branches', self.get_last_pr_comment(pr))

        pr.add_comment('/create_integration_branches')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)
        self.assertEqual(len(list(pr.get_comments())), 4)
        self.assertIn('Integration data created', self.get_last_pr_comment(pr))
        self.assertIn(
            'create_integration_branches', self.get_last_pr_comment(pr))

        options = self.bypass_all
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)

    def test_request_integration_branch_by_creating_pull_requests(self):
        """Test creating integration branches by creating pull requests

        1. Create a PR and verify that the appropriate message is sent
           regarding its creation
        2. Type `/create_integration_branches` and ensure the
           branches are created.
        3. Once the integration branches are created,
           ensure the bot is able to merge the PR.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_branches: false
always_create_integration_pull_requests: false
admins:
  - {admin}
""" # noqa
        options = self.bypass_all_but(['bypass_build_status'])
        pr = self.create_pr('feature/TEST-0069', 'development/4.3')
        with self.assertRaises(exns.RequestIntegrationBranches):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)

        pr.add_comment('/create_pull_requests')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)
        self.assertEqual(len(list(pr.get_comments())), 4)
        self.assertIn('Integration data created', self.get_last_pr_comment(pr))

        options = self.bypass_all
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)

        self.assertIn(
            'I have successfully merged the changeset',
            self.get_last_pr_comment(pr))

    def test_creation_integration_branch_by_approve(self):
        """Test pr.approve() to request integration branches creation.

        1. Create a PR and verify that the appropriate message is sent
           regarding its creation
        2. Ensure that author approval is required for the PR
        3. Approve the PR from the author's perspective and check if
           the integration branches are created.
        4. Once the integration branches are created,
           ensure the bot is able to merge the PR.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 0
always_create_integration_branches: false
admins:
  - {admin}
""" # noqa
        pr_1 = self.create_pr('feature/TEST-0069', 'development/4.3')
        pr_2 = self.create_pr('feature/TEST-0070', 'development/4.3')
        prs = [pr_1, pr_2]

        for pr in prs:
            options = self.bypass_all_but(['bypass_build_status',
                                           'bypass_author_approval'])
            with self.assertRaises(exns.ApprovalRequired):
                self.handle(pr.id, options=options, backtrace=True)

            self.assertEqual(len(list(pr.get_comments())), 3)

            self.assertIn(
                'Integration data created', list(pr.get_comments())[-2].text)

            self.assertIn(
                'Waiting for approval', self.get_last_pr_comment(pr))
            self.assertIn(
                'The following approvals are needed',
                self.get_last_pr_comment(pr))

            if pr.src_branch == "feature/TEST-0069":
                pr.approve()
            elif pr.src_branch == "feature/TEST-0070":
                pr.add_comment('/approve')

            with self.assertRaises(exns.BuildNotStarted):
                self.handle(
                    pr.id, settings=settings, options=options, backtrace=True)

            options = self.bypass_all
            with self.assertRaises(exns.SuccessMessage):
                self.handle(
                    pr.id, settings=settings, options=options, backtrace=True)

            self.assertIn(
                'I have successfully merged the changeset',
                self.get_last_pr_comment(pr))

    def test_integration_branch_creation_latest_branch(self):
        """Test there is no comment to request integration branches creation.

        1. Create a PR with the latest branch and check if there is no comment
           to request integration branches creation.
        2. Then, ensure the bot is able to merge the PR.

        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
always_create_integration_branches: false
admins:
  - {admin}
""" # noqa
        options = self.bypass_all_but(['bypass_build_status'])
        pr = self.create_pr('feature/TEST-0069', 'development/10')
        self.handle(pr.id, settings=settings, options=options)
        self.assertEqual(len(list(pr.get_comments())), 1)

        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)

        options = self.bypass_all
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id, settings=settings, options=options, backtrace=True)

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
robot: {robot}
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
robot: {robot}
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
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        integration_branches = [
            f'w/4/{src_branch}',
            f'w/5.1.4/{src_branch}',
            f'w/5.1/{src_branch}',
            f'w/5/{src_branch}',
            f'w/10.0.1/{src_branch}',
            f'w/10.0/{src_branch}',
            f'w/10/{src_branch}',
        ]
        # loop through all integration_branches but the latest
        for branch in integration_branches[:-1]:
            sha = self.gitrepo.cmd(f'git rev-parse origin/{branch}').rstrip()
            self.set_build_status(sha, 'SUCCESSFUL')
        sha1_w_10 = self.gitrepo.cmd(
            f'git rev-parse origin/{integration_branches[-1]}').rstrip()
        self.set_build_status(sha1=sha1_w_10, state='INPROGRESS')
        if self.args.git_host == 'github':
            pr.add_comment('@%s approve' % (self.args.robot_username))
        else:
            pr.approve()
        with self.assertRaises(exns.BuildInProgress):
            self.handle(pr.id, settings=settings,
                        options=options, backtrace=True)
        self.set_build_status(sha1=sha1_w_10, state='SUCCESSFUL')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(sha1_w_10, settings=settings,
                        options=options, backtrace=True)
        dev_branches = [
            'development/4.3',
            'development/4',
            'development/5.1',
            'development/5',
            'development/10.0',
            'development/10',
        ]
        for dev in dev_branches:
            branch = gwfb.branch_factory(self.gitrepo, dev)
            branch.checkout()
            self.gitrepo.cmd('git pull origin %s', dev)
            self.assertTrue(branch.includes_commit(pr.src_commit))

    def test_not_my_job_cases(self):
        feature_branch = 'feature/TEST-00002'
        from_branch = 'development/10.0'
        create_branch(self.gitrepo, feature_branch, from_branch=from_branch,
                      file_=True)
        pr = self.contributor_bb.create_pull_request(
            title='title', name='name', src_branch=feature_branch,
            dst_branch='release/10.0', close_source_branch=True, description=''
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
                            'hotfix/customer',
                            'hotfix/6.6.6.1',
                            'dependabot/npm_and_yarn/ui/lodash-4.17.13']:
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
        pr1 = self.create_pr('bugfix/TEST-0006', 'development/10.0',
                             file_='toto.txt')
        pr2 = self.create_pr('bugfix/TEST-0006-other', 'development/10.0',
                             file_='toto.txt')
        pr3 = self.create_pr('improvement/TEST-0006', 'development/10.0',
                             file_='toto.txt')
        pr4 = self.create_pr('improvement/TEST-0006-other', 'development/5',
                             file_='toto.txt')
        pr5 = self.create_pr('improvement/TEST-0006-last', 'development/4.3',
                             file_='toto.txt')

        # Start PR2 (create integration branches) first
        self.handle(pr2.id, self.bypass_all_but(['bypass_author_approval']))
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        # Pursue PR2 (conflict on branch development/10.0 vs. feature branch)
        try:
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                'between your branch `bugfix/TEST-0006-other` and the\n'
                'destination branch `development/10.0`.',
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
                'destination branch `development/10.0`',
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
                '`w/10.0/improvement/TEST-0006-other` with contents from '
                '`w/10.0.1/improvement/TEST-0006-other`\n'
                'and `development/10.0`',
                e.msg)
            # Bert-E MUST instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn(
                "git checkout -B w/10.0/improvement/TEST-0006", e.msg)
            self.assertIn(
                "git merge origin/w/10.0.1/improvement/TEST-0006", e.msg)
            self.assertIn(
                "git push -u origin w/10.0/improvement/TEST-0006", e.msg)
        else:
            self.fail("No conflict detected.")

        # Check that the empty w/10.0 branch of pr4 wasn't pushed.
        self.assertFalse(self.gitrepo.remote_branch_exists(
            "w/10.0/improvement/TEST-0006-other", True))

        try:
            self.handle(pr5.id, options=self.bypass_all, backtrace=True)
        except exns.Conflict as e:
            self.assertIn(
                '`w/10.0/improvement/TEST-0006-last` with contents from '
                '`w/10.0.1/improvement/TEST-0006-last`\n'
                'and `development/10.0`',
                e.msg)
            # Bert-E MUST instruct the user to modify the integration
            # branch with the same target as the original PR
            self.assertIn(
                "git checkout -B w/10.0/improvement/TEST-0006", e.msg)
            self.assertIn(
                "git merge origin/w/10.0.1/improvement/TEST-0006", e.msg)
            self.assertIn("git push -u origin w/10.0/improvement/TEST-0006",
                          e.msg)
        else:
            self.fail("No conflict detected.")

        # Check that the empty w/10.0 branch of pr5 wasn't pushed.
        self.assertFalse(self.gitrepo.remote_branch_exists(
            "w/10.0/improvement/TEST-0006-last", True))

        # But that the w/5.1 branch of pr5 was.
        self.assertTrue(self.gitrepo.remote_branch_exists(
            "w/5.1/improvement/TEST-0006-last", True))

    def test_commented_reviews(self):
        """ Test that change_requests block the gating
        This test relies on both approve() and dismiss() methods.
        """
        feature_branch = 'bugfix/TEST-0007-commented-changes'
        dst_branch = 'development/4.3'

        if self.args.git_host == 'bitbucket':
            self.skipTest("Comment-only Review are not supported" +
                          " on Bitbucket")

        # Having one change_requests blocks the gating on github
        pr = self.create_pr(feature_branch, dst_branch)

        # Check that Approvals are required at this point.
        # No further checks required.
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'],
                        backtrace=True)

        # Add a Commented review
        pr_peer = self.robot_bb.get_pull_request(pull_request_id=pr.id)
        pr_peer.comment_review()

        # Check that Approvals are still required, and that the request change
        # is mentionned
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'],
                        backtrace=True)

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
robot: {robot}
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
robot: {robot}
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
robot: {robot}
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
robot: {robot}
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

    def test_dismiss(self):
        """ Test that dismiss nullifies the provided review """
        feature_branch = 'bugfix/TEST-0007-request-changes'
        dst_branch = 'development/4.3'

        if self.args.git_host == 'bitbucket':
            self.skipTest("Change requests/dismissals are not supported" +
                          " on Bitbucket")

        # Having one change_requests blocks the gating on github
        pr = self.create_pr(feature_branch, dst_branch)

        # Check that Approvals are required at this point.
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        backtrace=True)
        self.assertNotIn('expecting changes', raised.exception.msg)

        # Add the required approvals
        if self.args.git_host == 'github':
            pr.add_comment('@%s approve' % (self.args.robot_username))
        else:
            pr.approve()
        pr_peer1 = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_peer1.approve()
        pr_peer2 = self.robot_bb.get_pull_request(pull_request_id=pr.id)
        review_peer2 = pr_peer2.approve()

        # Check that the PR is now passing.
        with self.assertRaises(exns.BuildNotStarted) as raised:
            self.handle(pr.id,
                        options=['bypass_jira_check'],
                        backtrace=True)

        # Dismiss one peer approval
        pr_peer2.dismiss(review_peer2)

        # Check that one peer approval is required again
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        backtrace=True)
        self.assertNotIn('expecting changes', raised.exception.msg)

    def test_change_requests(self):
        """ Test that change_requests block the gating
        This test relies on both approve() and dismiss() methods.
        """
        feature_branch = 'bugfix/TEST-0007-request-changes'
        dst_branch = 'development/4.3'

        if self.args.git_host == 'bitbucket':
            self.skipTest("Change requests/dismissals are not supported" +
                          " on Bitbucket")

        # test bert-e with only one required peer approval
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 0
required_peer_approvals: 1
admins:
  - {admin}
""" # noqa

        # Having one change_requests blocks the gating on github
        pr = self.create_pr(feature_branch, dst_branch)

        # Check that Approvals are required at this point.
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        self.assertNotIn('expecting changes', raised.exception.msg)

        # Add a change request from a second peer
        pr_peer2 = self.robot_bb.get_pull_request(pull_request_id=pr.id)
        review_peer2 = pr_peer2.request_changes()

        # Check that Approvals are still required, and that the request change
        # is mentionned
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        self.assertIn('expecting changes', raised.exception.msg)

        # Add the required approvals
        if self.args.git_host == 'github':
            pr.add_comment('@%s approve' % (self.args.robot_username))
        else:
            pr.approve()
        pr_peer1 = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_peer1.approve()

        # Check that only the change request is still blocking the PR
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        self.assertIn('expecting changes', raised.exception.msg)

        # Dismiss with the third user,
        # effectively nullifying the change request
        pr_peer2.dismiss(review_peer2)

        # Check that the PR is now passing.
        with self.assertRaises(exns.BuildNotStarted) as raised:
            self.handle(pr.id,
                        options=['bypass_jira_check'],
                        settings=settings, backtrace=True)

        # Add a change request again from the third user
        pr_peer2 = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        review_peer2 = pr_peer2.request_changes()

        # Check that he's blocking the process again
        with self.assertRaises(exns.ApprovalRequired) as raised:
            self.handle(pr.id, options=['bypass_jira_check'],
                        settings=settings, backtrace=True)
        self.assertIn('expecting changes', raised.exception.msg)

        # Approve with the third user,
        # effectively nullifying the change request
        pr_peer2.approve()

        # Check that the PR is now passing.
        with self.assertRaises(exns.SuccessMessage) as raised:
            self.handle(pr.id,
                        options=['bypass_jira_check',
                                 'bypass_build_status'],
                        settings=settings, backtrace=True)

    def test_branches_creation_main_pr_not_approved(self):
        """Test if Bert-e creates integration pull-requests when the main
        pull-request isn't approved.

        1. Create feature branch and create an unapproved pull request
        2. Run Bert-E on the pull request
        3. Check existence of integration branches

        """
        for feature_branch in ['bugfix/TEST-0008', 'bugfix/TEST-0008-label']:
            dst_branch = 'development/4.3'
            pr = self.create_pr(feature_branch, dst_branch)
            with self.assertRaises(exns.ApprovalRequired):
                self.handle(pr.id, options=['bypass_jira_check'],
                            backtrace=True)

            # check existence of integration branches
            for version in ['4', '5.1', '5', '10.0', '10']:
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

        pr = self.create_pr('bugfix/00067', 'development/10.0')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('improvement/i', 'development/4.3')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/free_text', 'development/10.0')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/free_text2', 'development/5.1')
        with self.assertRaises(exns.MissingJiraId):
            self.handle(pr.id, backtrace=True)

        pr = self.create_pr('bugfix/RONG-0001', 'development/10.0')
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
        if self.args.git_host != 'mock' and not self.args.disable_queues:
            self.skipTest('We can\'t bypass queues branches on githost')
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

        # Try force reset in enhanced bitbucket editor
        pr.add_comment("@{} force\\\\_reset".format(self.args.robot_username))
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
        self.gitrepo.cmd('git checkout w/10.0/bugfix/TEST-00001')
        self.gitrepo.cmd('echo plop > toto.txt')
        self.gitrepo.cmd('git add toto.txt')
        self.gitrepo.cmd('git commit -m "Integration commit 1"')
        self.gitrepo.cmd('git push origin w/10.0/bugfix/TEST-00001')

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
        comment = pr.add_comment('/wait')
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, backtrace=True)
        comment.delete()

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
        pr.add_comment('/help')
        with self.assertRaises(exns.HelpMessage):
            self.handle(pr.id, backtrace=True)

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
        comment = pr.add_comment('/helpp')
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        comment = pr.add_comment('@%s helpp' % self.args.robot_username)
        with self.assertRaises(exns.UnknownCommand):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)
        comment.delete()

        # test command args
        pr.add_comment('/help some arguments --hehe')
        with self.assertRaises(exns.HelpMessage):
            self.handle(pr.id, backtrace=True)

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
            '/bypass_author_approval\n'
            ' /bypass_peer_approval'
            ' /bypass_leader_approval'
            ' /bypass_build_status'
            ' /bypass_jira_check'
        )
        comment.delete()
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, options=['bypass_jira_check'], backtrace=True)

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

    def test_bypass_author_settings_errors(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approvall
    - bypass_build_status
    - bypass_peer_approval
"""  # noqa
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.IncorrectSettingsFile):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_build_status
    - bypass_peer_approval
"""  # noqa
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options_not_peer_approval(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_build_status
    """  # noqa
        # test bypass branch prefix through comment
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        pr_peer = self.robot_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options_not_peer_approval_failed(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_build_status
    """  # noqa
        # test bypass branch prefix through comment
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options_not_author_approval(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_build_status
    - bypass_peer_approval
    """  # noqa
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        pr.approve()
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options_not_author_approval_fail(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_build_status
    - bypass_peer_approval
    """  # noqa
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True)

    def test_bypass_author_options_build_status_failed(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_peer_approval
"""  # noqa
        # test bypass branch prefix through comment
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

    def test_bypass_author_options_build_status(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_peer_approvals: 1
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_peer_approval
"""  # noqa
        # test bypass branch prefix through comment
        pr = self.create_pr('bugfix/TEST-00081', 'development/5')

        # test build not started
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
                        settings=settings,
                        backtrace=True)
        except exns.BuildFailed as excp:
            self.assertIn(
                "did not succeed in branch `w/10.0/bugfix/TEST-00081`",
                excp.msg,
            )
        else:
            raise Exception('did not raise BuildFailed')

        # test build status inprogress
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 3, 'SUCCESSFUL')
        with self.assertRaises(exns.BuildInProgress):
            self.handle(pr.id,
                        settings=settings,
                        backtrace=True)

        # test bypass leader approval through comment
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        settings=settings,
                        backtrace=True)

    def test_bypass_author_options_leader_approval(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_author_approval
    - bypass_peer_approval
    - bypass_build_status
""" # noqa
        pr = self.create_pr('feature/TEST-00014', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )
        pr_admin = self.admin_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_admin.approve()
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

    def test_bypass_author_comment_check(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_jira_check
""" # noqa
        pr = self.create_pr('feature/TEST-0042', 'development/10')
        self.handle(pr.id, settings=settings)
        self.assertIs(len(list(pr.get_comments())), 2)
        self.assertIn('bypass_jira_check', self.get_last_pr_comment(pr))
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_author_approval
""" # noqa
        pr = self.create_pr('feature/TEST-0043', 'development/10')
        self.handle(pr.id, settings=settings)
        self.assertIs(len(list(pr.get_comments())), 2)
        self.assertIn('bypass_author_approval', self.get_last_pr_comment(pr))

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_peer_approval
""" # noqa
        pr = self.create_pr('feature/TEST-0044', 'development/10')
        self.handle(pr.id, settings=settings)
        self.assertIs(len(list(pr.get_comments())), 2)
        self.assertIn('bypass_peer_approval', self.get_last_pr_comment(pr))

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_build_status
""" # noqa
        pr = self.create_pr('feature/TEST-0045', 'development/10')
        self.handle(pr.id, settings=settings)
        self.assertIs(len(list(pr.get_comments())), 2)
        self.assertIn('bypass_build_status', self.get_last_pr_comment(pr))

    def test_bypass_author_jira(self):
        """
        Even with the wrong branch name with Jira it should pass
        Look at `test_inclusion_of_jira_issue` for the raise error
        """
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 2
project_leaders:
  - {admin}
pr_author_options:
  {contributor}:
    - bypass_jira_check
    - bypass_author_approval
    - bypass_build_status
    - bypass_peer_approval
    - bypass_leader_approval
"""  # noqa
        pr = self.create_pr('bugfix/00066', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

        pr = self.create_pr('bugfix/00067', 'development/10.0')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

        pr = self.create_pr('improvement/i', 'development/10.0')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

        pr = self.create_pr('bugfix/free_text', 'development/10.0')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

        pr = self.create_pr('bugfix/free_text2', 'development/10.0')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

        pr = self.create_pr('bugfix/RONG-0001', 'development/10.0')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                settings=settings,
                backtrace=True
            )

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

    # NOTE: test_missing_development_branch has been removed
    # because it's no longer relevant with the current cascade
    # behavior. After removing stabilization branches,
    # the cascade logic has become highly resilient and
    # simply skips missing versions rather than raising
    # DevBranchDoesNotExist. The cascade algorithm now:
    # 1. Only processes existing branches that it can find
    # 2. Gracefully skips any missing development/hotfix branches for a version
    # 3. Continues processing the remaining versions in the cascade
    # This makes DevBranchDoesNotExist nearly impossible
    # to trigger in normal operation, as the system will
    # only work with branches that actually exist rather than
    # expecting specific branches to be present.

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

            pr = self.create_pr('bugfix/TEST-00081', 'development/10.0')
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
                self.gitrepo.cmd('git checkout w/10.0/bugfix/TEST-00081')
                self.gitrepo.cmd('touch abc')
                self.gitrepo.cmd('git add abc')
                self.gitrepo.cmd('git commit -m "add new file"')
                self.gitrepo.cmd('git push origin')
                sha1 = self.gitrepo.cmd(
                    'git rev-parse w/10.0/bugfix/TEST-00081')

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
        pr = self.create_pr('bugfix/TEST-00081', 'development/5')

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
                "did not succeed in branch `w/10.0/bugfix/TEST-00081`",
                excp.msg,
            )
        else:
            raise Exception('did not raise BuildFailed')

        # test build status inprogress
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'INPROGRESS')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 3, 'SUCCESSFUL')
        with self.assertRaises(exns.BuildInProgress):
            self.handle(pr.id,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

        # test bypass leader approval through comment
        pr = self.create_pr('bugfix/TEST-00078', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        pr_admin.add_comment('@%s bypass_leader_approval' %
                             self.args.robot_username)
        print("pr.id", pr.id)
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
            url='https://builds.test.com/DEADBEEF'
        )
        for pr_id in range(pr.id + 1, pr.id + 5):
            self.set_build_status_on_pr_id(pr_id, 'SUCCESSFUL')

        with self.assertRaises(exns.BuildFailed) as err:
            childpr = self.robot_bb.get_pull_request(
                pull_request_id=pr.id + 1)
            self.handle(childpr.src_commit,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
            self.assertIn('https://builds.test.com/DEADBEEF', err.msg)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(childpr.src_commit,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

    def test_source_branch_history_changed(self):
        if self.args.git_host == 'github':
            self.skipTest("deleting a branch when a PR is open referencing it,"
                          "marks the PR as closed and make this test unusable")
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

    def test_github_actions_result_error(self):
        if self.args.git_host != 'github':
            self.skipTest("GitHub Actions is only supported with GitHub")

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: github_actions
always_create_integration_pull_requests: False
""" # noqa
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        add_file_to_branch(self.gitrepo,
                           'bugfix/TEST-00001',
                           'workflow-error.yml',
                           do_push=True,
                           folder='.github/workflows')
        add_file_to_branch(self.gitrepo,
                           'bugfix/TEST-00001',
                           'workflow.yml',
                           do_push=True,
                           folder='.github/workflows')

        for index in range(0, 60):
            try:
                with self.assertRaises(exns.BuildFailed):
                    self.handle(
                        pr.id, settings=settings,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)
            except Exception:
                if index == 59:
                    raise exns.BuildFailed()
                time.sleep(2)
            else:
                break

    def test_github_actions_result_fail(self):
        """
        To check the return of github action we are adding one workflow
        that will succeed and an other with a failure.
        We should have an build status error at the end.
        """
        if self.args.git_host != 'github':
            self.skipTest("GitHub Actions is only supported with GitHub")

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: github_actions
always_create_integration_pull_requests: False
"""  # noqa
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        add_file_to_branch(self.gitrepo,
                           'bugfix/TEST-00001',
                           'workflow-fail.yml',
                           do_push=True,
                           folder='.github/workflows')

        for index in range(0, 60):
            try:
                with self.assertRaises(exns.BuildFailed):
                    self.handle(
                        pr.id, settings=settings,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

            except Exception:
                if index == 59:
                    raise exns.BuildFailed()
                time.sleep(4)
            else:
                break

    def test_github_actions_result(self):
        if self.args.git_host != 'github':
            self.skipTest("GitHub Actions is only supported with GitHub")

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: github_actions
always_create_integration_pull_requests: False
""" # noqa
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        add_file_to_branch(self.gitrepo,
                           'bugfix/TEST-00001',
                           'workflow.yml',
                           do_push=True,
                           folder='.github/workflows')

        for index in range(0, 60):
            try:
                with self.assertRaises(exns.SuccessMessage):
                    self.handle(
                        pr.id, settings=settings,
                        options=self.bypass_all_but(['bypass_build_status']),
                        backtrace=True)

            except Exception:
                if index == 59:
                    raise exns.BuildFailed()
                time.sleep(2)
            else:
                break

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

    def test_success_message_content(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5.1')
        try:
            self.handle(pr.id, options=[
                'bypass_build_status',
                'bypass_leader_approval',
                'bypass_peer_approval',
                'bypass_author_approval',
                'bypass_jira_check'],
                backtrace=True)
        except exns.SuccessMessage as e:
            self.assertIn('* :heavy_check_mark: `development/5.1`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/5`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/10.0`', e.msg)
            self.assertIn('* :heavy_check_mark: `development/10`', e.msg)
            self.assertIn('* `development/4.3`', e.msg)
            self.assertIn('* `development/4`', e.msg)

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

        octopus_merge = git_utils.octopus_merge
        git_utils.octopus_merge = disturb_the_kraken

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
            git_utils.octopus_merge = octopus_merge

    def test_fallback_to_consecutive_merge(self):
        def disturb_the_kraken(dst, src1, src2):
            raise MergeFailedException()

        octopus_merge = git_utils.octopus_merge
        git_utils.octopus_merge = disturb_the_kraken

        try:
            pr = self.create_pr('bugfix/test-merge', 'development/4.3')
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id, options=self.bypass_all, backtrace=True)
        finally:
            git_utils.octopus_merge = octopus_merge

    def test_robust_merge(self):
        """Simulate a successful incorrect octopus merge.

        Check that the PR was still correctly merged
        (using sequential strategy).

        """
        octopus_merge = git_utils.octopus_merge

        sha1 = None

        def wrong_octopus_merge(dst, src1, src2):
            octopus_merge(dst, src1, src2)
            dst.checkout()
            dst.repo.cmd('echo plop >> tmp')
            dst.repo.cmd('git add tmp')
            dst.repo.cmd('git commit -m "extra commit"')
            nonlocal sha1
            sha1 = dst.repo.cmd('git log -n 1 --pretty="%H"')

        git_utils.octopus_merge = wrong_octopus_merge

        try:
            pr = self.create_pr('bugfix/test-merge', 'development/4.3')
            with self.assertRaises(exns.SuccessMessage):
                self.handle(pr.id, options=self.bypass_all, backtrace=True)

            assert sha1 is not None  # the function was called

            self.gitrepo.cmd('git fetch --prune')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/development/4.3 '
                             'origin/development/10.0')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/bugfix/test-merge '
                             'origin/development/4.3')
            self.gitrepo.cmd('git merge-base --is-ancestor '
                             'origin/bugfix/test-merge '
                             'origin/development/10.0')

            with self.assertRaises(CommandError):
                self.gitrepo.cmd('git merge-base --is-ancestor {} '
                                 'origin/development/10.0'
                                 .format(sha1))
        finally:
            git_utils.octopus_merge = octopus_merge

    def test_bitbucket_lag_on_pr_status(self):
        """Bitbucket can be a bit long to update a merged PR's status.

        Check that Bert-E handles this case nicely and returns before creating
        integration PRs.

        """
        try:
            real = gwf.early_checks

            pr = self.create_pr('bugfix/TEST-00081', 'development/10.0')
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

        exp_int_branches = [
            'w/4/bugfix/TEST-0001',
            'w/5.1.4/bugfix/TEST-0001',
            'w/5.1/bugfix/TEST-0001',
            'w/5/bugfix/TEST-0001',
            'w/10.0.1/bugfix/TEST-0001',
            'w/10.0/bugfix/TEST-0001',
            'w/10/bugfix/TEST-0001'
        ]
        int_prs = list(self.contributor_bb.get_pull_requests(
            src_branch=exp_int_branches)
        )

        self.gitrepo.cmd('git checkout bugfix/TEST-0001')
        self.gitrepo.cmd('git reset HEAD~1 --hard')
        self.gitrepo.cmd('git push origin -f bugfix/TEST-0001')

        with self.assertRaises(exns.BranchHistoryMismatch):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # Decline integration pull requests
        self.assertEqual(len(int_prs), 7)
        for ipr in int_prs:
            ipr.decline()

        # Delete integration branches
        for branch in exp_int_branches:
            self.gitrepo.push(f':{branch}')

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

    def test_branch_name_escape(self):
        """Make sure git api support branch names with
        special chars and doesn't interpret them in bash.

        """
        unescaped = 'bugfix/dangerous-branch-name-${TEST}'

        # Bypass git-api to create the branch (explicit escape of the bad char)
        branch_name = unescaped.replace(r'$', r'\$')
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
robot: {robot}
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
robot: {robot}
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
        pr = self.create_pr('bugfix/TEST-00003', 'development/10')
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
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
robot: {robot}
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
robot: {robot}
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
robot: {robot}
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

    def test_branches_have_diverged(self):
        settings = DEFAULT_SETTINGS + 'max_commit_diff: 5'
        pr = self.create_pr('feature/time-warp', 'development/10.0')

        for idx in range(6):
            tpr = self.create_pr('feature/%s' % idx, 'development/10.0')
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
            Let the robot propagate the change to w/10.0
            Remove the development/5.1 branch
            Wake up the robot on the PR with bypass_all

        Expected result:
            The PR gets merged into development/4.3 and development/10.0

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
        self.gitrepo.cmd('git tag 5.1.5')
        self.gitrepo.cmd(
            'git push origin :development/5.1 --tags')

        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/4.3')
        self.gitrepo.cmd('git merge-base --is-ancestor origin/feature/foo '
                         'origin/development/10.0')

    def test_merge_again_in_earlier_dev_branch(self):
        """Check Bert-E can handle merging again in an earlier dev branch.

        Steps:
            Create a PR targetting development/4.3
            Create another PR with same branch targetting development/5.1
            Merge the second PR with bypass_all
            Merge the first PR with bypass_all

        Expected result:
            Both PRs get merged and the commit is available in development/4.3,
            development/5.1 and development/10.0.

        """
        pr1 = self.create_pr('bugfix/TEST-0001', 'development/4.3')
        pr2 = self.create_pr('bugfix/TEST-0001', 'development/5.1',
                             reuse_branch=True)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        # Tracking BERTE-504
        # Github and Bitbucket don't allow creating a PR
        # where the destination is equal to the source.
        # This might be annoying when we would want to backport a fix.
        # As a workaround we can deactivate the creation
        # of integration PR to avoid it.
        # So here, in this test, when not using the mocked git host,
        # we ensure that the real one fails as expected and Skip the tests
        if self.args.git_host != 'mock':
            try:
                self.handle(pr1.id, options=self.bypass_all, backtrace=True)
            except requests.exceptions.HTTPError as exp:
                resp = exp.response
                if self.args.git_host == 'bitbucket':
                    self.assertEqual(400, resp.status_code)
                    self.assertEqual('There are no changes to be pulled',
                                     resp.json()['error']['message'])
                elif self.args.git_host == 'github':
                    self.assertEqual(422, resp.status_code)
                    self.assertEqual('Validation Failed',
                                     resp.json()['message'])
        else:
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
robot: {robot}
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
robot: {robot}
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
robot: {robot}
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

    def test_upper_case_users(self):
        """Test a pull request with usernames defined in upper case."""

        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
need_author_approval: True
required_leader_approvals: 1
required_peer_approvals: 1
admins:
  - %s
project_leaders:
  - %s
  - another_leader_handle
""" % (self.args.admin_username.upper(), self.args.contributor_username.upper()) # noqa
        if self.args.git_host == 'bitbucket':
            self.skipTest('As bitbucket now use user ids which are case'
                          'sensitive, this test make no sense anymore')
        pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        pr_peer = self.admin_bb.get_pull_request(
            pull_request_id=pr.id)
        pr_peer.approve()
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

        if self.args.git_host == 'github':
            pr.add_comment('@%s approve' % (self.args.robot_username))
        else:
            pr.approve()
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        options=[
                            'bypass_jira_check',
                            'bypass_build_status',
                        ],
                        settings=settings,
                        backtrace=True)

    def test_comment_authored(self):
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_peer_approvals: 1
need_author_approval: True
admins:
  - {admin}
""" # noqa
        pr = self.create_pr('bugfix/TEST-994', 'development/4.3')
        pr_peer = self.admin_bb.get_pull_request(pull_request_id=pr.id)
        comment = pr_peer.add_comment('@%s approve' %
                                      self.args.robot_username)
        # Ensure that only authors can use this option
        with self.assertRaises(exns.NotAuthor):
            self.handle(pr.id,
                        settings=settings,
                        options=[
                            'bypass_build_status',
                            'bypass_jira_check',
                        ],
                        backtrace=True)
        comment.delete()
        pr_peer.approve()
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id,
                        settings=settings,
                        options=[
                            'bypass_build_status',
                            'bypass_jira_check',
                        ],
                        backtrace=True)
        pr.add_comment('@%s approve' % self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id,
                        settings=settings,
                        options=[
                            'bypass_build_status',
                            'bypass_jira_check',
                        ],
                        backtrace=True)

    def test_author_approval_option(self):
        """Test the author approval option."""
        settings = """
repository_owner: {owner}
repository_slug: {slug}
repository_host: {host}
robot: {robot}
robot_email: nobody@nowhere.com
pull_request_base_url: https://bitbucket.org/{owner}/{slug}/bar/pull-requests/{{pr_id}}
commit_base_url: https://bitbucket.org/{owner}/{slug}/commits/{{commit_id}}
build_key: pre-merge
required_leader_approvals: 1
required_peer_approvals: 1
need_author_approval: True
admins:
  - {admin}
project_leaders:
  - {contributor}
  - another_leader_handle
""" # noqa
        pr = self.create_pr('bugfix/TEST-00003', 'development/4.3')
        pr_admin = self.admin_bb.get_pull_request(
            pull_request_id=pr.id)
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(
                pr.id,
                options=[
                    'bypass_jira_check',
                    'bypass_build_status',
                ],
                settings=settings,
                backtrace=True)
        pr_admin.approve()
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(
                pr.id,
                options=[
                    'bypass_jira_check',
                    'bypass_build_status',
                ],
                settings=settings,
                backtrace=True)
        pr.add_comment('@%s approve' % self.args.robot_username)
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                options=[
                    'bypass_jira_check',
                    'bypass_build_status',
                ],
                settings=settings,
                backtrace=True)

    def test_disable_version_checks(self):
        """Test the version checks disabling option."""
        settings = DEFAULT_SETTINGS + 'disable_version_checks: true'
        pr = self.create_pr('bugfix/TEST-2048', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                options=[
                    'bypass_author_approval',
                    'bypass_peer_approval',
                    'bypass_leader_approval',
                    'bypass_build_status',
                ],
                settings=settings,
                backtrace=True)

    def test_comments_sorted(self):
        """Test that the comments on the githost are sorted by date.

        Bert-E no repeat strategy relies on the fact that comment must be
        sorted by creation date.

        """
        pr = self.create_pr('bugfix/TEST-42', 'development/4.3')

        for i in range(20):
            pr.add_comment('comment number %s' % i)

        comments = list(pr.get_comments())
        comments_sorted = sorted(comments, key=lambda c: c.created_on)
        for i in range(len(comments)):
            self.assertEqual(comments[i], comments_sorted[i])

    def test_dependabot_pr(self):
        """Test a simple dependabot PR.

            Improvements to this test will be made later, per example
            automatically bypass author approval.
        """
        pr = self.create_pr('dependabot/npm_and_yarn/ui/lodash-4.17.13',
                            'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(
                pr.id,
                options=[
                    # bypass_author to be removed once we support it properly
                    'bypass_author_approval',
                    'bypass_jira_check',
                    'bypass_leader_approval',
                    'bypass_build_status',
                    'bypass_peer_approval',
                ],
                backtrace=True
            )

    def test_init_message(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.handle(pr.id)
        init_message = pr.comments[0].text
        assert f"Hello {pr.author}" in init_message
        # Assert init message the list of options
        for option in self.bypass_all:
            assert option in init_message
        for command in ['help', 'reset']:
            assert command in init_message

    def test_set_bot_status(self):
        """Test Bert-E's capability to its own status on PRs"""
        settings = DEFAULT_SETTINGS + "send_bot_status: true"
        pr = self.create_pr('bugfix/TEST-01', 'development/4.3')
        self.handle(pr.id)
        assert self.get_build_status(
            pr.src_commit, key="bert-e") == "NOTSTARTED"
        self.handle(pr.id, settings=settings)
        assert self.get_build_status(
            pr.src_commit, key="bert-e") == "failure"
        self.handle(pr.id, settings=settings, options=["bypass_jira_check"])
        assert self.get_build_status(
            pr.src_commit, key="bert-e") == "queued"
        self.handle(pr.id, settings=settings, options=self.bypass_all)

    def test_dev_major_only(self):
        """Test Bert-E's capability to handle a development/x branch."""
        # Can we merge a dev/4.3 with a dev/4
        pr1 = self.create_pr('bugfix/TEST-01', 'development/4.3')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)
        # Can we merge directly on a dev/4
        pr3 = self.create_pr('bugfix/TEST-03', 'development/4')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr3.id, options=self.bypass_all, backtrace=True)
        # Ensure the gitwaterflow is set correctly between all the branches
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd(
            'git merge-base --is-ancestor '
            'origin/development/4.3 '
            'origin/development/4'
        )
        with self.assertRaises(CommandError):
            self.gitrepo.cmd(
                'git merge-base --is-ancestor '
                'origin/development/4 '
                'origin/development/4.3'
            )

    def test_admin_self_bypass(self):
        """Test an admin can bypass its own PR."""
        feature_branch = 'feature/TEST-00001'
        from_branch = 'development/4.3'
        create_branch(self.gitrepo, feature_branch,
                      from_branch=from_branch, file_=True)
        pr = self.admin_bb.create_pull_request(
            title="title",
            name="name",
            src_branch=feature_branch,
            dst_branch=from_branch,
            description="",
        )
        # Expect a jira check
        with self.assertRaises(exns.IncorrectFixVersion):
            self.handle(pr.id, backtrace=True)
        # Ensure peers cannot bypass the jira check without admin credentials
        peer = self.contributor_bb.get_pull_request(pull_request_id=pr.id)
        comment = peer.add_comment('/bypass_jira_check')
        # Expect a lack of credentials
        with self.assertRaises(exns.NotEnoughCredentials):
            self.handle(pr.id, backtrace=True)
        comment.delete()
        # Ensure the admin can bypass its own PR
        pr.add_comment('/bypass_jira_check')
        with self.assertRaises(exns.ApprovalRequired):
            self.handle(pr.id, backtrace=True)
        pr.add_comment('/bypass_peer_approval')
        pr.approve()
        with self.assertRaises(exns.BuildNotStarted):
            self.handle(pr.id, backtrace=True)
        pr.add_comment('/bypass_build_status')
        with self.assertRaises(exns.SuccessMessage):
            self.handle(pr.id, backtrace=True)


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
                    'q/w/{pr}/4.3/{name}',
                    'q/w/{pr}/5.1/{name}',
                    'q/w/{pr}/10.0/{name}'
                ]
            elif problem[pr]['dst'] == 'development/5.1':
                branches = [
                    'q/w/{pr}/5.1/{name}',
                    'q/w/{pr}/10.0/{name}'
                ]
            elif problem[pr]['dst'] == 'development/10.0':
                branches = [
                    'q/w/{pr}/10.0/{name}'
                ]
            elif problem[pr]['dst'] == 'hotfix/4.2.17':
                branches = [
                    'q/w/{pr}/4.2.17.1/{name}'
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
                    .cmd('git branch -r --list "origin/q/w/[0-9]*/*"')
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
                 gwfb.branch_factory(FakeGitRepo(), 'development/10.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'hotfix/4.3.18'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/4.3'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/5.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/10.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'hotfix/5.1.4'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/5.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/10.0')],

                [gwfb.branch_factory(FakeGitRepo(), 'hotfix/10.0.1'),
                 gwfb.branch_factory(FakeGitRepo(), 'development/10.0')],
            ],
            force_merge=False)
        for qbranch in qbranches:
            qc._add_branch(gwfb.branch_factory(self.gitrepo, qbranch))
        return qc

    def test_queue_branch(self):
        with self.assertRaises(exns.BranchNameInvalid):
            self.queue_branch("q/4.3/feature/RELENG-001-plop")

        qbranch = gwfb.branch_factory(FakeGitRepo(), "q/5.1")
        self.assertEqual(type(qbranch), gwfb.QueueBranch)
        self.assertEqual(qbranch.version_t, (5, 1))
        self.assertEqual(qbranch.version, "5.1")
        self.assertEqual(qbranch.major, 5)
        self.assertEqual(qbranch.minor, 1)

    def test_qint_branch(self):
        with self.assertRaises(exns.BranchNameInvalid):
            self.qint_branch("q/6.3")

        with self.assertRaises(exns.BranchNameInvalid):
            self.qint_branch("q/6.2/feature/RELENG-001-plop")

        qint_branch = gwfb.branch_factory(FakeGitRepo(),
                                          "q/w/10/6.2/feature/RELENG-001-plop")
        self.assertEqual(type(qint_branch), gwfb.QueueIntegrationBranch)
        self.assertEqual(qint_branch.version_t, (6, 2))
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
            2: {'dst': 'development/10.0', 'src': 'feature/foo',
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
            ((4, 3), {
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((4, None), {
                gwfb.QueueBranch: self.queue_branch('q/4'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((5, 1, 4), {
                gwfb.QueueBranch: self.queue_branch('q/5.1.4'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((5, 1), {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((5, None), {
                gwfb.QueueBranch: self.queue_branch('q/5'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((10, 0, 1), {
                gwfb.QueueBranch: self.queue_branch('q/10.0.1'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((10, 0), {
                gwfb.QueueBranch: self.queue_branch('q/10.0'),
                gwfb.QueueIntegrationBranch: []
            }),
            ((10, None), {
                gwfb.QueueBranch: self.queue_branch('q/10'),
                gwfb.QueueIntegrationBranch: []
            }),
        ])

    @property
    def standard_solution(self):
        """This is the solution to the standard problem."""
        return OrderedDict([
            ((4, 3), {
                gwfb.QueueBranch: self.queue_branch('q/4.3'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/4.3/improvement/bar2'),
                    self.qint_branch('q/w/1/4.3/improvement/bar')
                ]
            }),
            ((4, None), {
                gwfb.QueueBranch: self.queue_branch('q/4'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/4/improvement/bar2'),
                    self.qint_branch('q/w/1/4/improvement/bar')
                ]
            }),
            ((5, 1, 4), {
                gwfb.QueueBranch: self.queue_branch('q/5.1.4'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/5.1.4/improvement/bar2'),
                    self.qint_branch('q/w/1/5.1.4/improvement/bar')
                ]
            }),
            ((5, 1), {
                gwfb.QueueBranch: self.queue_branch('q/5.1'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/5.1/improvement/bar2'),
                    self.qint_branch('q/w/11/5.1/bugfix/bar'),
                    self.qint_branch('q/w/1/5.1/improvement/bar')
                ]
            }),
            ((5, None), {
                gwfb.QueueBranch: self.queue_branch('q/5'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/5/improvement/bar2'),
                    self.qint_branch('q/w/11/5/bugfix/bar'),
                    self.qint_branch('q/w/1/5/improvement/bar')
                ]
            }),
            ((10, 0, 1), {
                gwfb.QueueBranch: self.queue_branch('q/10.0.1'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/10.0.1/improvement/bar2'),
                    self.qint_branch('q/w/11/10.0.1/bugfix/bar'),
                    self.qint_branch('q/w/1/10.0.1/improvement/bar')
                ]
            }),
            ((10, 0), {
                gwfb.QueueBranch: self.queue_branch('q/10.0'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/10.0/improvement/bar2'),
                    self.qint_branch('q/w/11/10.0/bugfix/bar'),
                    self.qint_branch('q/w/9/10.0/feature/foo'),
                    self.qint_branch('q/w/1/10.0/improvement/bar')
                ]
            }),
            ((10, None), {
                gwfb.QueueBranch: self.queue_branch('q/10'),
                gwfb.QueueIntegrationBranch: [
                    self.qint_branch('q/w/16/10/improvement/bar2'),
                    self.qint_branch('q/w/11/10/bugfix/bar'),
                    self.qint_branch('q/w/9/10/feature/foo'),
                    self.qint_branch('q/w/1/10/improvement/bar')
                ]
            }),
        ])

    def test_queueing_standard_problem(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_queues, self.standard_solution)

    def test_queueing_standard_problem_reverse(self):
        qbranches = self.submit_problem(self.standard_problem)
        qc = self.feed_queue_collection(reversed(qbranches))
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_queues, self.standard_solution)

    def test_queueing_standard_problem_without_octopus(self):
        # monkey patch to skip octopus merge in favor of regular 2-way merges
        gwfi.octopus_merge = git_utils.consecutive_merge
        gwfq.octopus_merge = git_utils.consecutive_merge

        try:
            qbranches = self.submit_problem(self.standard_problem)
            qc = self.feed_queue_collection(qbranches)
            qc.finalize()
            qc.validate()
            self.assertEqual(qc._queues, self.standard_solution)
            self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
            self.assertEqual(qc.mergeable_prs, [1, 9, 11, 16])
            self.assertEqual(qc.mergeable_queues, self.standard_solution)
        finally:
            gwfi.octopus_merge = git_utils.octopus_merge
            gwfq.octopus_merge = git_utils.octopus_merge

    def test_queueing_last_pr_build_not_started(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {}
        solution = deepcopy(self.standard_solution)
        solution[(4, 3)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(4, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1, 4)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, None)][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_queueing_last_pr_build_failed(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'pipeline': 'FAILED'}
        solution = deepcopy(self.standard_solution)
        solution[(4, 3)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(4, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1, 4)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, None)][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11])
        self.assertEqual(qc.mergeable_queues, solution)

    def test_queueing_last_pr_other_key(self):
        problem = deepcopy(self.standard_problem)
        problem[4]['status'][2] = {'other': 'SUCCESSFUL'}
        solution = deepcopy(self.standard_solution)
        solution[(4, 3)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(4, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1, 4)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(5, None)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0, 1)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, 0)][gwfb.QueueIntegrationBranch].pop(0)
        solution[(10, None)][gwfb.QueueIntegrationBranch].pop(0)
        qbranches = self.submit_problem(problem)
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        qc.validate()
        self.assertEqual(qc._queues, self.standard_solution)
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11])
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
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [1, 9, 11, 16])
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
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
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
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
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
        self.assertEqual(qc.queued_prs, [1, 9, 11, 16])
        self.assertEqual(qc.mergeable_prs, [])
        self.assertEqual(qc.mergeable_queues, self.empty_solution)

    def test_queueing_oldest_branch_fails(self):
        status = {'pipeline': 'SUCCESSFUL', 'other': 'FAILED'}
        problem = OrderedDict({
            1: {'dst': 'development/4.3', 'src': 'improvement/bar',
                'status': [status] * 3},
            2: {'dst': 'development/10.0', 'src': 'feature/foo',
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
            qc.mergeable_prs == [1, 7, 9, 13]

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
        branches = ['q/4.3', 'q/5.1', 'q/10.0']
        qc = self.feed_queue_collection(branches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueNotInSync])

    def test_validation_masterq_on_dev(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/10.0')
        self.gitrepo.cmd('git reset --hard development/10.0')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.MasterQueueLateVsInt,
                                       exns.QueueInclusionIssue])

    def test_validation_masterq_late(self):
        qbranches = self.submit_problem(self.standard_problem)
        self.gitrepo.cmd('git checkout q/10.0')
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
        add_file_to_branch(self.gitrepo, 'q/w/16/5.1/improvement/bar2',
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
        qbranches.remove('q/w/1/4.3/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp, [exns.QueueIncomplete])

    def test_validation_with_missing_middle_intq(self):
        qbranches = self.submit_problem(self.standard_problem)
        qbranches.remove('q/w/1/5.1/improvement/bar')
        qc = self.feed_queue_collection(qbranches)
        qc.finalize()
        with self.assertRaises(exns.IncoherentQueues) as excp:
            qc.validate()
        self.assert_error_codes(excp,
                                [exns.QueueInconsistentPullRequestsOrder])

    def test_notify_pr_on_queue_fail(self):
        pr = self.create_pr('bugfix/TEST-01', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)
        branch = f"q/w/{pr.id}/4.3/{pr.src_branch}"
        self.set_build_status_on_branch_tip(branch, 'INPROGRESS')
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)
        self.set_build_status_on_branch_tip(branch, 'FAILED')
        with self.assertRaises(exns.QueueBuildFailed):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)
        # get last comment
        comment = list(pr.get_comments())[-1].text
        assert "Queue build failed" in comment

    def test_pr_and_merge_on_three_digit_branch(self):
        """Test that PRs can be created and
        merged on three-digit development branches."""
        pr = self.create_pr('bugfix/TEST-01', 'development/10.0.1')

        # First handle should queue the PR
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        queue_branches = [
            f'q/w/{pr.id}/10.0.1/{pr.src_branch}',
            f'q/w/{pr.id}/10.0/{pr.src_branch}',
            f'q/w/{pr.id}/10/{pr.src_branch}',
        ]

        # Set build status on all queue branches
        for branch in queue_branches:
            self.set_build_status_on_branch_tip(branch, 'SUCCESSFUL')

        # Second handle should merge successfully
        with self.assertRaises(exns.Merged):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # Verify the PR was merged
        assert pr.status == 'MERGED'

    def test_system_nominal_case(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5')
        self.handle(pr.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # add a commit to w/5.1 branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/10.0.1/bugfix/TEST-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        self.gitrepo.cmd('git push origin')
        sha1_w_10_0_1 = self.gitrepo.cmd(
            'git rev-parse w/10.0.1/bugfix/TEST-00001').rstrip()

        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # get the new sha1 on w/10.0 (set_build_status_on_pr_id won't
        # detect the new commit in mocked mode)
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/10.0/bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        sha1_w_10_0 = self.gitrepo.cmd(
            'git rev-parse w/10.0/bugfix/TEST-00001').rstrip()

        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/10/bugfix/TEST-00001')
        self.gitrepo.cmd('git pull')
        sha1_w_10 = self.gitrepo.cmd(
            'git rev-parse w/10/bugfix/TEST-00001').rstrip()

        # check expected branches exist
        self.gitrepo.cmd('git fetch --prune')
        expected_branches = [
            'q/w/1/5/bugfix/TEST-00001',
            'q/w/1/10.0/bugfix/TEST-00001',
            'q/w/1/10/bugfix/TEST-00001',
        ]

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch))

        # set build status
        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_10_0_1, state='SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_10_0, state='SUCCESSFUL')
        self.set_build_status(sha1=sha1_w_10, state='FAILED')
        with self.assertRaises(exns.QueueBuildFailed):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.QueueBuildFailed):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

        self.set_build_status(sha1=sha1_w_10, state='INPROGRESS')
        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

        self.set_build_status(sha1=sha1_w_10, state='SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

        # check validity of repo and branches
        for branch in ['q/5', 'q/10.0', 'q/10']:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch))
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True))
        for dev in ['development/5', 'development/10.0.1', 'development/10.0',
                    'development/10']:
            branch = gwfb.branch_factory(self.gitrepo, dev)
            branch.checkout()
            self.gitrepo.cmd('git pull origin %s', dev)
            self.assertTrue(branch.includes_commit(pr.src_commit))
            if dev == 'development/5':
                self.assertFalse(branch.includes_commit(sha1_w_10_0))
            else:
                self.assertTrue(branch.includes_commit(sha1_w_10_0_1))
                self.gitrepo.cmd('cat abc')

        last_comment = pr.comments[-1].text
        self.assertIn('I have successfully merged', last_comment)

    def test_system_missing_integration_queue_before_in_queue(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/4.3')

        self.gitrepo.cmd('git push origin :q/w/1/5.1/bugfix/TEST-00001')

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
        pr = self.create_pr('bugfix/TEST-00001', 'development/10.0')
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
        pr = self.create_pr('bugfix/TEST-00001', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')

        # delete integration branch
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/10')
        intb = gwfb.branch_factory(self.gitrepo, 'w/10/bugfix/TEST-00001')
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
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        # delete integration queues of pr1
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/10.0')
        intq1 = gwfb.branch_factory(
            self.gitrepo, 'q/w/1/10.0/bugfix/TEST-00001')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/3/10.0/bugfix/TEST-00002', 'SUCCESSFUL')

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(sha1, options=self.bypass_all, backtrace=True)

        # check the content of pr1 is not merged
        dev.checkout()
        self.gitrepo.cmd('git pull origin development/10.0')
        self.assertFalse(dev.includes_commit(pr1.src_commit))

    def test_delete_main_queues(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        # delete main queue branch
        self.gitrepo.cmd('git fetch')
        dev = gwfb.branch_factory(self.gitrepo, 'development/10.0')
        intq1 = gwfb.branch_factory(self.gitrepo, 'q/10.0')
        intq1.checkout()
        dev.checkout()
        intq1.remove(do_push=True)

        with self.assertRaises(exns.IncoherentQueues):
            self.handle(pr.src_commit, options=self.bypass_all, backtrace=True)

    def test_feature_branch_augmented_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/10')
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
        self.gitrepo.cmd('git checkout q/10')
        self.gitrepo.cmd('git pull')
        self.gitrepo.cmd('cat abc')

    def test_feature_branch_rewritten_after_queued(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/10')
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
        pr = self.create_pr('bugfix/TEST-00001', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')

        # Add a new commit
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout w/10/bugfix/TEST-00001')
        self.gitrepo.cmd('touch abc')
        self.gitrepo.cmd('git add abc')
        self.gitrepo.cmd('git commit -m "add new file"')
        sha1 = Branch(self.gitrepo,
                      'w/10/bugfix/TEST-00001').get_latest_commit()
        self.gitrepo.cmd('git push origin')

        with self.assertRaises(exns.Merged):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        with self.assertRaises(exns.NothingToDo):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.gitrepo.cmd('git fetch')
        # Check the additional commit was not merged
        self.assertFalse(
            Branch(self.gitrepo, 'development/10').includes_commit(sha1))

    def test_integration_branches_dont_follow_dev(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/5')
        # create integration branches but don't queue yet
        self.handle(pr1.id,
                    options=self.bypass_all_but(['bypass_build_status']))

        # get the sha1's of integration branches
        self.gitrepo.cmd('git fetch')
        sha1s = dict()
        for version in ['10.0', '10']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/TEST-00001', version)
            self.gitrepo.cmd('git pull')
            sha1s[version] = self.gitrepo \
                .cmd('git rev-parse w/%s/bugfix/TEST-00001', version) \
                .rstrip()

        # merge some other work
        pr2 = self.create_pr('bugfix/TEST-00002', 'development/10.0')
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
        for version in ['10.0', '10']:
            self.gitrepo.cmd('git checkout w/%s/bugfix/TEST-00001', version)
            self.gitrepo.cmd('git pull')
            self.assertEqual(
                sha1s[version],
                self.gitrepo
                    .cmd('git rev-parse w/%s/bugfix/TEST-00001', version)
                    .rstrip())

    def test_new_dev_branch_appears(self):
        pr = self.create_pr('bugfix/TEST-00001', 'development/5.1')
        with self.assertRaises(exns.Queued):
            self.handle(pr.id, options=self.bypass_all, backtrace=True)

        self.set_build_status_on_pr_id(pr.id, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 1, 'SUCCESSFUL')
        self.set_build_status_on_pr_id(pr.id + 2, 'SUCCESSFUL')

        # introduce a new version, but not its queue branch
        self.gitrepo.cmd('git fetch')
        self.gitrepo.cmd('git checkout development/10.0')
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

    def test_pr_dev_and_hotfix_with_hotfix_merged_first(self):
        self.gitrepo.cmd('git tag 10.0.0.0')
        self.gitrepo.cmd('git push --tags')

        pr0 = self.create_pr('bugfix/TEST-00000', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr0.id, options=self.bypass_all, backtrace=True)
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/10')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)
        pr2 = self.create_pr('bugfix/TEST-00002', 'hotfix/10.0.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr0.id, pr1.id, pr2.id})

        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0/bugfix/TEST-00000' % pr0.id, 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00000' % pr0.id, 'FAILED')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00001' % pr1.id, 'FAILED')
        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr0.id, pr1.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')

        with self.assertRaises(exns.QueueBuildFailed):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr0.id, pr1.id})

        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')

        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), set())

    def test_pr_dev_and_hotfix_with_dev_merged_first(self):
        self.gitrepo.cmd('git tag 10.0.0.0')
        self.gitrepo.cmd('git push --tags')

        pr0 = self.create_pr('bugfix/TEST-00000', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr0.id, options=self.bypass_all, backtrace=True)
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/10')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)
        pr2 = self.create_pr('bugfix/TEST-00002', 'hotfix/10.0.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr0.id, pr1.id, pr2.id})

        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00002' % pr2.id, 'FAILED')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), set())

    def test_pr_dev_and_hotfix_merged_in_the_same_time(self):
        self.gitrepo.cmd('git tag 10.0.0.0')
        self.gitrepo.cmd('git push --tags')

        pr0 = self.create_pr('bugfix/TEST-00000', 'development/10.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr0.id, options=self.bypass_all, backtrace=True)
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/10')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)
        pr2 = self.create_pr('bugfix/TEST-00002', 'hotfix/10.0.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr0.id, pr1.id, pr2.id})

        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00002' % pr2.id, 'SUCCESSFUL')

        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), set())

    def test_pr_hotfix_alone(self):
        self.gitrepo.cmd('git tag 10.0.0.0')
        self.gitrepo.cmd('git push --tags')

        pr0 = self.create_pr('bugfix/TEST-00000', 'hotfix/10.0.0')
        with self.assertRaises(exns.Queued):
            self.handle(pr0.id, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr0.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00000' % pr0.id, 'FAILED')
        with self.assertRaises(exns.QueueBuildFailed):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr0.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00000' % pr0.id, 'INPROGRESS')
        with self.assertRaises(exns.NothingToDo):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr0.id})

        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.0.1/bugfix/TEST-00000' % pr0.id, 'SUCCESSFUL')
        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), set())

    def test_pr_hotfix_and_three_digit_dev_branch_together(self):
        """Test that a hotfix PR and a three-digit
        development branch PR can be queued together."""
        # Set up a tag needed for hotfix branch
        self.gitrepo.cmd('git tag 10.0.2.0')
        self.gitrepo.cmd('git push --tags')

        # Create the hotfix branch from the tag
        self.gitrepo.cmd('git checkout -b hotfix/10.0.2 10.0.2.0')
        self.gitrepo.cmd('git push -u origin hotfix/10.0.2')

        # Create a PR targeting a hotfix branch
        pr_hotfix = self.create_pr('bugfix/TEST-HOTFIX', 'hotfix/10.0.2')
        with self.assertRaises(exns.Queued):
            self.handle(pr_hotfix.id, options=self.bypass_all, backtrace=True)

        # Create a PR targeting a three-digit development branch
        pr_dev = self.create_pr('feature/TEST-DEV', 'development/5.1.4')
        with self.assertRaises(exns.Queued):
            self.handle(pr_dev.id, options=self.bypass_all, backtrace=True)

        # Verify both PRs are in the queue
        self.assertEqual(self.prs_in_queue(), {pr_hotfix.id, pr_dev.id})

        # Set build status to successful on all queue branches for hotfix PR
        # Hotfix PR should create queue branches for 4.3.19.1
        hotfix_queue_branches = [
            f'q/w/{pr_hotfix.id}/10.0.2.1/{pr_hotfix.src_branch}',
        ]

        # Set build status to successful on all queue branches for dev PR
        dev_queue_branches = [
            f'q/w/{pr_dev.id}/5.1.4/{pr_dev.src_branch}',
            f'q/w/{pr_dev.id}/5.1/{pr_dev.src_branch}',
            f'q/w/{pr_dev.id}/5/{pr_dev.src_branch}',
            f'q/w/{pr_dev.id}/10.0.1/{pr_dev.src_branch}',
            f'q/w/{pr_dev.id}/10.0/{pr_dev.src_branch}',
            f'q/w/{pr_dev.id}/10/{pr_dev.src_branch}',
        ]

        # Set successful build status on hotfix queue branches
        hotfix_sha1 = None
        for branch in hotfix_queue_branches:
            hotfix_sha1 = self.set_build_status_on_branch_tip(
                branch, 'SUCCESSFUL')

        # Set successful build status on dev queue branches
        for branch in dev_queue_branches:
            self.set_build_status_on_branch_tip(
                branch, 'SUCCESSFUL')

        # Both PRs should merge successfully when we handle their SHA1s
        # This triggers the queue merge logic
        with self.assertRaises(exns.Merged):
            self.handle(hotfix_sha1, options=self.bypass_all, backtrace=True)

        # Verify both PRs were merged and queue is empty
        self.assertEqual(self.prs_in_queue(), set())
        self.assertEqual(pr_hotfix.status, 'MERGED')
        self.assertEqual(pr_dev.status, 'MERGED')

    def test_multi_branch_queues_2(self):
        pr1 = self.create_pr('bugfix/TEST-00001', 'development/5')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-00002', 'development/10')
        with self.assertRaises(exns.Queued):
            self.handle(pr2.id, options=self.bypass_all, backtrace=True)

        self.assertEqual(self.prs_in_queue(), {pr1.id, pr2.id})

        self.set_build_status_on_branch_tip(
            'q/w/%d/5/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0.1/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10.0/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00001' % pr1.id, 'SUCCESSFUL')
        sha1 = self.set_build_status_on_branch_tip(
            'q/w/%d/10/bugfix/TEST-00002' % pr2.id, 'FAILED')
        with self.assertRaises(exns.Merged):
            self.handle(sha1, options=self.bypass_all, backtrace=True)
        self.assertEqual(self.prs_in_queue(), {pr2.id})

    def test_queue_conflict(self):
        pr1 = self.create_pr('bugfix/TEST-0006', 'development/10.0',
                             file_='toto.txt')
        with self.assertRaises(exns.Queued):
            self.handle(pr1.id, options=self.bypass_all, backtrace=True)

        pr2 = self.create_pr('bugfix/TEST-0006-other', 'development/10.0',
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
        settings['jira_token'] = 'dummy_jira_token'
        settings['cmd_line_options'] = options
        settings['backtrace'] = backtrace
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
            settings=settings
        )
        return job

    def process_sha1_job(self, sha1, status=None, **settings):
        job = self.make_sha1_job(sha1, **settings)
        return self.process_job(job, status)

    def test_berte_duplicate_pr_job(self):
        self.init_berte()
        pr = self.create_pr('bugfix/TEST-0001', 'development/10.0')
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
        pr = self.create_pr('bugfix/TEST-0001', 'development/10.0')
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
            'q/w/1/4.3/bugfix/TEST-00001',
            'q/w/1/4/bugfix/TEST-00001',
            'q/w/1/5.1/bugfix/TEST-00001',
            'q/w/1/5/bugfix/TEST-00001',
            'q/w/1/10.0/bugfix/TEST-00001',
            'q/w/1/10/bugfix/TEST-00001',
            'w/4/bugfix/TEST-00001',
            'w/5.1/bugfix/TEST-00001',
            'w/5/bugfix/TEST-00001',
            'w/10.0/bugfix/TEST-00001',
            'w/10/bugfix/TEST-00001'
        ]
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        sha1_q_10_0 = self.gitrepo._remote_branches['q/10.0']

        self.process_sha1_job(sha1_q_10_0, 'NothingToDo')

        status = self.berte.status.get('merge queue', OrderedDict())
        self.assertIn(1, status)
        self.assertEqual(len(status[1]), 8)
        versions = tuple(version for version, _ in status[1])
        self.assertEqual(versions, ('10', '10.0', '10.0.1', '5',
                                    '5.1', '5.1.4', '4', '4.3'))
        for _, sha1 in status[1]:
            self.set_build_status(sha1=sha1, state='SUCCESSFUL')
        self.process_sha1_job(sha1_q_10_0, 'Merged')

        merged_pr = self.berte.status.get('merged PRs', [])
        self.assertEqual(len(merged_pr), 1)
        self.assertEqual(merged_pr[0]['id'], 1)

    def test_status_with_queue_without_octopus(self):
        # monkey patch to skip octopus merge in favor of regular 2-way merges
        gwfi.octopus_merge = git_utils.consecutive_merge
        gwfq.octopus_merge = git_utils.consecutive_merge

        try:
            self.init_berte(options=self.bypass_all)
            pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
            self.process_pr_job(pr, 'Queued')

            # check expected branches exist
            self.gitrepo.cmd('git fetch --prune')
            expected_branches = [
                'q/w/1/4.3/bugfix/TEST-00001',
                'q/w/1/4/bugfix/TEST-00001',
                'q/w/1/5.1/bugfix/TEST-00001',
                'q/w/1/5/bugfix/TEST-00001',
                'q/w/1/10.0/bugfix/TEST-00001',
                'q/w/1/10/bugfix/TEST-00001',
                'w/4/bugfix/TEST-00001',
                'w/5.1/bugfix/TEST-00001',
                'w/5/bugfix/TEST-00001',
                'w/10.0/bugfix/TEST-00001',
                'w/10/bugfix/TEST-00001'
            ]
            for branch in expected_branches:
                self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                                'branch %s not found' % branch)

            sha1_q_10_0 = self.gitrepo._remote_branches['q/10.0']

            self.process_sha1_job(sha1_q_10_0, 'NothingToDo')

            status = self.berte.status.get('merge queue', OrderedDict())
            versions = tuple(version for version, _ in status[1])
            for _, sha1 in status[1]:
                self.set_build_status(sha1=sha1, state='SUCCESSFUL')
            self.assertEqual(versions, ('10', '10.0', '10.0.1',
                                        '5', '5.1', '5.1.4', '4', '4.3'))
            self.process_sha1_job(sha1_q_10_0, 'Merged')

            merged_pr = self.berte.status.get('merged PRs', [])
            self.assertEqual(len(merged_pr), 1)
            self.assertEqual(merged_pr[0]['id'], 1)
        finally:
            gwfi.octopus_merge = git_utils.octopus_merge
            gwfq.octopus_merge = git_utils.octopus_merge

    def test_job_create_branch_dev_queues_disabled(self):
        """Test creation of development branches with queues disabled."""
        self.init_berte(options=self.bypass_all, disable_queues=True)
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/1.0'},
                bert_e=self.berte),
            'JobSuccess'
        )
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/5.5'},
                bert_e=self.berte),
            'JobSuccess'
        )
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/11.0'},
                bert_e=self.berte),
            'JobSuccess'
        )
        expected_branches = [
            'development/1.0',
            'development/4.3',
            'development/5.1',
            'development/5.5',
            'development/10.0',
            'development/11.0',
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        self.gitrepo.cmd('git fetch')
        pr = self.create_pr('feature/TEST-9999', 'development/1.0')
        self.process_pr_job(pr, 'SuccessMessage')

    def test_job_delete_branch_dev_queues_disabled(self):
        """Test deletion of development branches with queues disabled."""
        self.init_berte(options=self.bypass_all, disable_queues=True)
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/5.1'},
                bert_e=self.berte),
            'JobSuccess'
        )
        expected_branches = [
            ('development/4.3', self.assertTrue),
            ('development/5.1', self.assertFalse),
            ('development/10.0', self.assertTrue),
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch, func in expected_branches:
            func(self.gitrepo.remote_branch_exists(branch),
                 'branch %s incorrect' % branch)

        self.gitrepo.cmd('git fetch')
        pr = self.create_pr('feature/TEST-9999', 'development/4.3')
        self.process_pr_job(pr, 'SuccessMessage')

    def test_job_create_branch_dev_failure_cases(self):
        """Test creation of development branches."""
        self.init_berte(options=self.bypass_all)
        pr = self.create_pr('feature/TEST-9999', 'development/10.0')

        # cannot branch when branch already exists
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/5.1'},
                bert_e=self.berte),
            'NothingToDo'
        )

        # cannot branch when branch is not a GWF dest branch
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'bar'},
                bert_e=self.berte),
            'JobFailure'
        )
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'q/7.0'},
                bert_e=self.berte),
            'JobFailure'
        )

        # cannot branch when a tag archiving a branch already exists
        self.gitrepo.cmd('git tag 7.0')
        self.gitrepo.cmd('git push --tags')
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/7.0'},
                bert_e=self.berte),
            'JobFailure'
        )

        self.gitrepo._get_remote_branches(force=True)
        sha1_4_3 = self.gitrepo._remote_branches['development/4.3']
        sha1_pr = self.gitrepo._remote_branches['feature/TEST-9999']

        # cannot branch from an invalid sha1
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/8.0',
                    'branch_from': 'coucou'},
                bert_e=self.berte),
            'JobFailure'
        )

        # cannot branch from a sha1 that does not belong to a dest branch
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/5.5',
                    'branch_from': sha1_pr},  # inclusion error
                bert_e=self.berte),
            'JobFailure'
        )
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/12.0',  # force merge attack!
                    'branch_from': sha1_pr},
                bert_e=self.berte),
            'JobFailure'
        )

        # cannot branch from a sha1 too early
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/5.3',
                    'branch_from': sha1_4_3},
                bert_e=self.berte),
            'JobFailure'
        )

        # cannot add dev at begining or middle of cascade if queued data
        self.process_pr_job(pr, 'Queued')
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/2.0'},
                bert_e=self.berte),
            'JobFailure'
        )
        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/5.9'},
                bert_e=self.berte),
            'JobFailure'
        )

    def test_job_delete_branch_dev_failure_cases(self):
        """Test deletion of development branches."""
        self.init_berte(options=self.bypass_all)

        # cannot del branch when branch does not exist
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/9.9'},
                bert_e=self.berte),
            'NothingToDo'
        )

        # cannot del a non GWF dest branch
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'bar'},
                bert_e=self.berte),
            'JobFailure'
        )
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'q/7.0'},
                bert_e=self.berte),
            'JobFailure'
        )

        # cannot del branch when a tag archiving a branch already exists
        self.gitrepo.cmd('git tag 4.3')
        self.gitrepo.cmd('git push origin 4.3')
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/4.3'},
                bert_e=self.berte),
            'JobFailure'
        )
        self.gitrepo.cmd('git push origin :4.3')

        # cannot del branch if queued data
        pr = self.create_pr('feature/TEST-9999', 'development/5.1')
        self.process_pr_job(pr, 'Queued')
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/5.1'},
                bert_e=self.berte),
            'JobFailure'
        )
        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/10.0'},
                bert_e=self.berte),
            'JobFailure'
        )

    def test_job_create_branch_dev_start(self):
        """Test creation of development branches at start of cascade."""
        self.init_berte(options=self.bypass_all)

        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/2.9'},
                bert_e=self.berte),
            'JobSuccess'
        )
        # check where this branch points
        self.gitrepo._get_remote_branches(force=True)
        self.assertEqual(
            self.gitrepo._remote_branches['development/2.9'],
            self.gitrepo._remote_branches['development/4.3.18']
        )

        self.gitrepo.cmd('git fetch')
        pr = self.create_pr('feature/TEST-9999', 'development/2.9')
        self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'development/2.9',
            'development/4.3',
            'development/5.1',
            'development/10.0',
            'q/2.9',
            'q/4.3',
            'q/5.1',
            'q/10.0',
            'q/w/1/2.9/feature/TEST-9999',
            'q/w/1/4.3/feature/TEST-9999',
            'q/w/1/5.1/feature/TEST-9999',
            'q/w/1/10.0/feature/TEST-9999',
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

    def test_job_create_branch_dev_middle(self):
        """Test creation of development branches at end of cascade."""
        self.init_berte(options=self.bypass_all)

        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/5.2',
                    'branch_from': ''},
                bert_e=self.berte),
            'JobSuccess'
        )
        # check where this branch points
        self.gitrepo._get_remote_branches(force=True)
        self.assertEqual(
            self.gitrepo._remote_branches['development/5.2'],
            self.gitrepo._remote_branches['development/5.1']
        )

        self.gitrepo.cmd('git fetch')
        pr = self.create_pr('feature/TEST-9999', 'development/5.1')
        self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'development/4.3',
            'development/5.1',
            'development/5.2',
            'development/10.0',
            'q/5.1',
            'q/5.2',
            'q/10.0',
            'q/w/1/5.1/feature/TEST-9999',
            'q/w/1/5.2/feature/TEST-9999',
            'q/w/1/10.0/feature/TEST-9999',
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # check one last PR to check the repo is in order
        pr = self.create_pr('feature/TEST-9998', 'development/4.3')
        self.process_pr_job(pr, 'Queued')

    def test_job_create_branch_dev_end(self):
        """Test creation of development branches at end of cascade."""
        self.init_berte(options=self.bypass_all)

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/4.3')
            for n in range(1, 4)
        ]

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        self.process_job(
            CreateBranchJob(
                settings={'branch': 'development/11.3'},
                bert_e=self.berte),
            'JobSuccess'
        )
        # check where this branch points
        self.gitrepo._get_remote_branches(force=True)
        self.assertEqual(
            self.gitrepo._remote_branches['development/11.3'],
            self.gitrepo._remote_branches['development/10']
        )

        # consume the 3 expected pr jobs sitting in the job queue
        self.assertEqual(self.berte.task_queue.unfinished_tasks, 3)
        for n in range(1, 4):
            job = self.berte.process_task()
            self.assertEqual(job.status, 'Queued')

        self.gitrepo.cmd('git fetch')
        pr = self.create_pr('feature/TEST-9997', 'development/11.3')
        self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'development/4.3',
            'development/5.1',
            'development/10.0',
            'development/11.3',
            'q/4.3',
            'q/10.0',
            'q/11.3',
            'q/w/1/4.3/feature/TEST-01',
            'q/w/1/4/feature/TEST-01',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/5/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/1/10/feature/TEST-01',
            'q/w/1/11.3/feature/TEST-01',
            'q/w/2/4.3/feature/TEST-02',
            'q/w/2/4/feature/TEST-02',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/5/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/2/10/feature/TEST-02',
            'q/w/2/11.3/feature/TEST-02',
            'q/w/3/4.3/feature/TEST-03',
            'q/w/3/4/feature/TEST-03',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/5/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
            'q/w/3/10/feature/TEST-03',
            'q/w/3/11.3/feature/TEST-03',
            'q/w/28/11.3/feature/TEST-9997',
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # merge everything so that branches advance
        # and also to allow creation of intermediary dest branches
        sha1_middle = self.gitrepo._remote_branches['q/10']
        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'Merged')

        # test a branch creation with source specified
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/10.1',
                    'branch_from': sha1_middle},
                bert_e=self.berte),
            'JobSuccess')
        self.process_job(
            CreateBranchJob(
                settings={
                    'branch': 'development/10.2',
                    'branch_from': 'development/10'},
                bert_e=self.berte),
            'JobSuccess')

        # check where these branches point
        self.gitrepo._get_remote_branches(force=True)
        self.assertEqual(
            self.gitrepo._remote_branches['development/10.1'],
            sha1_middle
        )
        self.assertEqual(
            self.gitrepo._remote_branches['development/10.2'],
            self.gitrepo._remote_branches['development/10']
        )

        # one last PR to check the repo is in order
        pr = self.create_pr('feature/TEST-9999', 'development/4.3')
        self.process_pr_job(pr, 'Queued')

    def test_job_delete_branch(self):
        """Test deletion of development branches."""
        self.init_berte(options=self.bypass_all)

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/5.1')
            for n in range(1, 4)
        ]

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'development/4.3'},
                bert_e=self.berte),
            'JobSuccess'
        )

        self.assertEqual(self.berte.task_queue.unfinished_tasks, 0)

        pr = self.create_pr('feature/TEST-9998', 'development/5.1')
        self.process_pr_job(pr, 'Queued')

        expected_branches = [
            ('development/4.3', self.assertFalse),
            ('q/4.3', self.assertFalse),

            ('development/5.1', self.assertTrue),
            ('development/10.0', self.assertTrue),
            ('q/10.0', self.assertTrue),
            ('q/w/1/5.1/feature/TEST-01', self.assertTrue),
            ('q/w/1/5/feature/TEST-01', self.assertTrue),
            ('q/w/1/10.0/feature/TEST-01', self.assertTrue),
            ('q/w/1/10/feature/TEST-01', self.assertTrue),
            ('q/w/2/5.1/feature/TEST-02', self.assertTrue),
            ('q/w/2/5/feature/TEST-02', self.assertTrue),
            ('q/w/2/10.0/feature/TEST-02', self.assertTrue),
            ('q/w/2/10/feature/TEST-02', self.assertTrue),
            ('q/w/3/5.1/feature/TEST-03', self.assertTrue),
            ('q/w/3/5/feature/TEST-03', self.assertTrue),
            ('q/w/3/10.0/feature/TEST-03', self.assertTrue),
            ('q/w/3/10/feature/TEST-03', self.assertTrue),
            ('q/w/16/5.1/feature/TEST-9998', self.assertTrue),
            ('q/w/16/5/feature/TEST-9998', self.assertTrue),
            ('q/w/16/10.0/feature/TEST-9998', self.assertTrue),
            ('q/w/16/10/feature/TEST-9998', self.assertTrue),
        ]
        self.gitrepo._get_remote_branches(force=True)
        for branch, func in expected_branches:
            func(self.gitrepo.remote_branch_exists(branch),
                 'branch %s error' % branch)

        self.gitrepo.cmd('git fetch')
        tags = self.gitrepo.cmd('git tag').split('\n')
        expected_tags = ['4.3']
        for tag in expected_tags:
            self.assertIn(tag, tags)

    def test_job_delete_hotfix_branch_with_pr_queued(self):
        """Test deletion of development and hotfix branches."""
        self.init_berte(options=self.bypass_all)

        # Create a couple PRs and queue them
        pr = self.create_pr('feature/TEST-666', 'hotfix/4.2.17')
        self.process_pr_job(pr, 'Queued')

        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'hotfix/4.2.17'},
                bert_e=self.berte),
            'JobFailure'
        )

    def test_job_delete_hotfix_branch(self):
        """Test deletion of development and hotfix branches."""
        self.init_berte(options=self.bypass_all)

        self.process_job(
            DeleteBranchJob(
                settings={'branch': 'hotfix/4.2.17'},
                bert_e=self.berte),
            'JobSuccess'
        )

    def test_job_create_branch_hotfix(self):
        self.init_berte(options=self.bypass_all)
        self.gitrepo.cmd('git tag 4.1.27.0')
        self.gitrepo.cmd('git push --tags')

        self.process_job(
            CreateBranchJob(
                settings={'branch': 'hotfix/4.1.27'},
                bert_e=self.berte),
            'JobSuccess'
        )

        self.gitrepo.cmd('git fetch --all')
        sha1_origin = self.gitrepo \
                          .cmd('git rev-parse refs/tags/4.1.27.0') \
                          .rstrip()
        sha1_branch = self.gitrepo \
                          .cmd('git rev-parse '
                               'refs/remotes/origin/hotfix/4.1.27') \
                          .rstrip()
        self.assertEqual(sha1_branch, sha1_origin)

        self.process_job(
            CreateBranchJob(
                settings={'branch': 'hotfix/4.1.28',
                          'branch_from': 'development/4.3'},
                bert_e=self.berte),
            'JobSuccess'
        )

        self.gitrepo.cmd('git fetch --all')
        sha1_origin = self.gitrepo \
                          .cmd('git rev-parse '
                               'refs/remotes/origin/development/4.3') \
                          .rstrip()
        sha1_branch = self.gitrepo \
                          .cmd('git rev-parse '
                               'refs/remotes/origin/hotfix/4.1.28') \
                          .rstrip()
        self.assertEqual(sha1_branch, sha1_origin)

    def test_job_evaluate_pull_request(self):
        self.init_berte(options=self.bypass_all)

        # test behaviour when PR does not exist
        self.process_job(
            EvalPullRequestJob(settings={'pr_id': 1}, bert_e=self.berte),
            'JobFailure'
        )

        pr = self.create_pr('bugfix/TEST-00001', 'development/4.3')
        self.process_job(
            EvalPullRequestJob(settings={'pr_id': pr.id}, bert_e=self.berte),
            'Queued'
        )

    def test_job_force_merge_queues(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            ForceMergeQueuesJob(bert_e=self.berte,
                                settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'NothingToDo'
        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'NothingToDo')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/4.3')
            for n in range(1, 4)
        ]

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        # put a mix of build statuses in the queue
        self.gitrepo._get_remote_branches()
        sha1_q_4_3 = self.gitrepo._remote_branches['q/4.3']
        self.set_build_status(sha1=sha1_q_4_3, state='FAILED')
        sha1_q_5_1 = self.gitrepo._remote_branches['q/5.1']
        self.set_build_status(sha1=sha1_q_5_1, state='INPROGRESS')
        # (leave q/10.0 blank)

        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'Merged')

        # Check that the PRs are merged
        self.gitrepo._get_remote_branches(force=True)
        sha1_q_10_0 = self.gitrepo._remote_branches['q/10.0']
        sha1_dev_10_0 = self.gitrepo._remote_branches['development/10.0']
        self.assertEqual(sha1_q_10_0, sha1_dev_10_0)

    def test_job_force_merge_queues_with_hotfix(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            ForceMergeQueuesJob(bert_e=self.berte,
                                settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'NothingToDo'
        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'NothingToDo')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/4.3')
            for n in range(1, 4)
        ]

        # Add a hotfix PR
        prs.append(self.create_pr('feature/TEST-666', 'hotfix/4.2.17'))

        for pr in prs:
            self.process_pr_job(pr)

        # put a mix of build statuses in the queue
        self.gitrepo._get_remote_branches()
        sha1_q_4_3 = self.gitrepo._remote_branches['q/4.3']
        self.set_build_status(sha1=sha1_q_4_3, state='FAILED')
        sha1_q_5_1 = self.gitrepo._remote_branches['q/5.1']
        self.set_build_status(sha1=sha1_q_5_1, state='INPROGRESS')
        # (leave q/10.0 blank)

        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'Merged')

        # Check that the PRs are merged
        self.gitrepo._get_remote_branches(force=True)
        sha1_q_10_0 = self.gitrepo._remote_branches['q/10.0']
        sha1_dev_10_0 = self.gitrepo._remote_branches['development/10.0']
        self.assertEqual(sha1_q_10_0, sha1_dev_10_0)
        sha1_q_4_2_17_1 = self.gitrepo._remote_branches['q/4.2.17.1']
        sha1_hotfix_4_2_17 = self.gitrepo._remote_branches['hotfix/4.2.17']
        self.assertEqual(sha1_q_4_2_17_1, sha1_hotfix_4_2_17)

    def test_job_delete_queues(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            DeleteQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'JobSuccess'
        self.process_job(DeleteQueuesJob(bert_e=self.berte), 'JobSuccess')

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
            'q/10.0',
            'q/w/1/4.3/feature/TEST-01',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/2/4.3/feature/TEST-02',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/3/4.3/feature/TEST-03',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        self.process_job(DeleteQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Check that the queues are destroyed
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True),
                             'branch %s still exists' % branch)

        # check nothing more pending
        self.assertTrue(self.berte.task_queue.empty())

    def test_job_delete_queues_with_hotfix(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            DeleteQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'JobSuccess'
        self.process_job(DeleteQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/4.3')
            for n in range(1, 4)
        ]

        # Add a hotfix PR
        prs.append(self.create_pr('feature/TEST-666', 'hotfix/4.2.17'))

        for pr in prs:
            self.process_pr_job(pr)

        expected_branches = [
            'q/4.2.17.1',
            'q/4.3',
            'q/5.1',
            'q/10.0',

        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        self.process_job(DeleteQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Check that the queues are destroyed
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True),
                             'branch %s still exists' % branch)

        # check nothing more pending
        self.assertTrue(self.berte.task_queue.empty())

    def test_job_rebuild_queues(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            RebuildQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'JobSuccess'
        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

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
            'q/10.0',
            'q/w/1/4.3/feature/TEST-01',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/2/4.3/feature/TEST-02',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/3/4.3/feature/TEST-03',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # Put a 'wait' command on one of the PRs to exclude it from the queue
        excluded, *requeued = prs
        excluded.add_comment("@%s wait" % self.args.robot_username)

        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

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
            'q/10.0',
            'q/w/2/4.3/feature/TEST-02',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/3/4.3/feature/TEST-03',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
        ]

        excluded_branches = [
            'q/w/1/4.3/feature/TEST-01',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
        ]

        # Check that all 'requeued' PRs are queued again
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch, True),
                            'branch %s not found' % branch)

        # Check that the excluded PR is *not* queued.
        for branch in excluded_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch),
                             "branch %s shouldn't exist" % branch)

    def test_job_rebuild_queues_with_hotfix(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            RebuildQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'JobSuccess'
        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/10.0')
            for n in range(1, 5)
        ]

        # Add a hotfix PR
        prs.append(self.create_pr('feature/TEST-666', 'hotfix/4.2.17'))

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'q/4.2.17.1',
            'q/10.0',
            'q/10',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/1/10/feature/TEST-01',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/2/10/feature/TEST-02',
            'q/w/3/10.0/feature/TEST-03',
            'q/w/3/10/feature/TEST-03',
            'q/w/5/4.2.17.1/feature/TEST-666',

        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # Put a 'wait' command on one of the PRs to exclude it from the queue
        excluded, *requeued = prs
        excluded.add_comment("@%s wait" % self.args.robot_username)

        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

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
            'q/4.2.17.1',
            'q/10.0',
            'q/10',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/2/10/feature/TEST-02',
            'q/w/3/10.0/feature/TEST-03',
            'q/w/3/10/feature/TEST-03',
            'q/w/5/4.2.17.1/feature/TEST-666',
        ]

        excluded_branches = [
            'q/w/1/10.0/feature/TEST-01',
            'q/w/1/10/feature/TEST-01',
        ]

        # Check that all 'requeued' PRs are queued again
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch, True),
                            'branch %s not found' % branch)

        # Check that the excluded PR is *not* queued.
        for branch in excluded_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch),
                             "branch %s shouldn't exist" % branch)

    def test_job_rebuild_queues_without_hotfix(self):
        self.init_berte(options=self.bypass_all)

        # When queues are disabled, Bert-E should respond with 'NotMyJob'
        self.process_job(
            RebuildQueuesJob(bert_e=self.berte, settings={'use_queue': False}),
            'NotMyJob'
        )

        # When there is no queue, Bert-E should respond with 'JobSuccess'
        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Create a couple PRs and queue them
        prs = [
            self.create_pr('feature/TEST-{:02d}'.format(n), 'development/5.1')
            for n in range(1, 4)
        ]

        # create a 5.0.3 tag on hotfix/5.0.3
        self.gitrepo.cmd('git tag 5.0.3 origin/hotfix/5.0.3')
        self.gitrepo.cmd('git push --tags')
        # Add a hotfix PR
        prs.append(self.create_pr('feature/TEST-666', 'hotfix/5.0.3'))

        for pr in prs:
            self.process_pr_job(pr, 'Queued')

        expected_branches = [
            'q/5.0.3.1',
            'q/5.1',
            'q/5',
            'q/10.0',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/5/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/1/10/feature/TEST-01',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/5/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/2/10/feature/TEST-02',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/5/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
            'q/w/3/10/feature/TEST-03',
            'q/w/4/5.0.3.1/feature/TEST-666',
        ]
        # Check that all PRs are queued

        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)

        # Put a 'wait' command on one of the PRs to exclude it from the queue
        *requeued, excluded = prs
        excluded.add_comment("@%s wait" % self.args.robot_username)

        self.process_job(RebuildQueuesJob(bert_e=self.berte), 'JobSuccess')

        # Check that the robot is going to be waken up on all of the previously
        # queued prs.
        self.assertEqual(len(self.berte.task_queue.queue), len(prs))

        while not self.berte.task_queue.empty():
            self.berte.process_task()

        expected_branches = [
            'q/5.1',
            'q/5',
            'q/10.0',
            'q/w/1/5.1/feature/TEST-01',
            'q/w/1/5/feature/TEST-01',
            'q/w/1/10.0/feature/TEST-01',
            'q/w/1/10/feature/TEST-01',
            'q/w/2/5.1/feature/TEST-02',
            'q/w/2/5/feature/TEST-02',
            'q/w/2/10.0/feature/TEST-02',
            'q/w/2/10/feature/TEST-02',
            'q/w/3/5.1/feature/TEST-03',
            'q/w/3/5/feature/TEST-03',
            'q/w/3/10.0/feature/TEST-03',
            'q/w/3/10/feature/TEST-03',
        ]

        excluded_branches = [
            'q/5.0.3.1',
            'q/w/4/5.0.3.1/feature/TEST-666',

        ]

        # Check that all 'requeued' PRs are queued again
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch, True),
                            'branch %s not found' % branch)

        # Check that the excluded PR is *not* queued.
        for branch in excluded_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch),
                             "branch %s shouldn't exist" % branch)

    def test_no_need_queuing(self):
        """Expect Bert-E to skip the queue when there is no need to queue."""

        # Two PRs created at the same time
        # At the moment they were created they are both up to date with the
        # destination branch
        self.init_berte(
            options=self.bypass_all, skip_queue_when_not_needed=True)
        first_pr = self.create_pr('feature/TEST-1', 'development/4.3')
        second_pr = self.create_pr('feature/TEST-2', 'development/4.3')
        # The first PR is ready to merge, and is expected to merge directly
        # without going through the queue.
        self.process_pr_job(first_pr, 'SuccessMessage')
        # When the second PR is merged we expect it to go through the queue
        # as it is no longer up to date with the destination branch.
        self.process_pr_job(second_pr, 'Queued')
        # At this point the repository should now contain queue branches.
        # We force the merge to get everything setup according for the next
        # scenario.
        self.process_job(ForceMergeQueuesJob(bert_e=self.berte), 'Merged')
        # We expect the PR to be merged so there should be nothing left to do.
        self.process_pr_job(second_pr, 'NothingToDo')
        # We get the local repo setup for a third PR that should be up to
        # date with the latest changes.
        self.gitrepo.cmd('git checkout development/4.3')
        self.gitrepo.cmd('git branch --set-upstream-to=origin/development/4.3')
        self.gitrepo.cmd('git pull')
        third_pr = self.create_pr('feature/TEST-3', 'development/4.3')
        fourth_pr = self.create_pr('feature/TEST-4', 'development/4.3')
        # Just like the first PR, we expect this one to be merged directly.
        self.process_pr_job(third_pr, 'SuccessMessage')
        # Now we want to know if when the queue is a bit late is Bert-E
        # capable of reeastablishing the Queue in order, and queue PR number 4.
        self.process_pr_job(fourth_pr, 'Queued')

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

    def test_flakiness(self):
        if self.args.git_host != 'bitbucket':
            self.skipTest("flakiness test is only supported on bitbucket")
        self.init_berte()
        pr = self.create_pr('bugfix/TEST-00429', 'development/4.3')
        self.process_bitbucket_pr_job_with_429(pr)
        last_comment = pr.get_comments()[-1].text
        self.assertTrue(FLAKINESS_MESSAGE_TITLE in last_comment)

    def test_delete_queue_no_major(self):
        self.init_berte(options=self.bypass_all)
        # delete the development/10 branch
        self.gitrepo.cmd('git push origin :development/10')
        expected_branches = [
            'q/10.0',
        ]
        for i in range(3):
            pr = self.create_pr('feature/TEST-000%d' % i, 'development/10.0')
            self.process_pr_job(pr, 'Queued')
            expected_branches.append(f'q/w/{pr.id}/10.0/feature/TEST-000{i}')
        for branch in expected_branches:
            self.assertTrue(self.gitrepo.remote_branch_exists(branch),
                            'branch %s not found' % branch)
        self.process_job(DeleteQueuesJob(bert_e=self.berte), 'JobSuccess')
        for branch in expected_branches:
            self.assertFalse(self.gitrepo.remote_branch_exists(branch, True),
                             'branch %s still exists' % branch)


def main():
    parser = argparse.ArgumentParser(description='Launches Bert-E tests.')
    parser.add_argument(
        'owner',
        help='Owner of test repository (aka Bitbucket/GitHub team)')
    parser.add_argument('robot_username', type=str.lower,
                        help='Robot Bitbucket/GitHub username')
    parser.add_argument('robot_password',
                        help='Robot Bitbucket/GitHub password')
    parser.add_argument('contributor_username', type=str.lower,
                        help='Contributor Bitbucket/GitHub username')
    parser.add_argument('contributor_password',
                        help='Contributor Bitbucket/GitHub password')
    parser.add_argument('admin_username', type=str.lower,
                        help='Privileged user Bitbucket/GitHub username')
    parser.add_argument('admin_password',
                        help='Privileged user Bitbucket/GitHub password')
    parser.add_argument('tests', nargs='*', help='run only these tests')
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
    jira_api.JiraIssue = jira_api_mock.JiraIssue

    if RepositoryTests.args.verbose:
        # only the message in the format string will be displayed
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
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
