#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import requests
import sys
import unittest
import logging

from bitbucket_api import (Client, PullRequest,
                           Repository as BitbucketRepository)
import wall_e
from wall_e_exceptions import (BranchDoesNotAcceptFeatures,
                               CommentAlreadyExists,
                               NothingToDo,
                               AuthorApprovalRequired,
                               Conflict,
                               BranchNameInvalid,
                               HelpMessage,
                               ParentNotFound,
                               StatusReport,
                               InitMessage)
from git_api import Repository as GitRepository
from simplecmd import cmd

WALL_E_USERNAME = wall_e.WALL_E_USERNAME
WALL_E_EMAIL = wall_e.WALL_E_EMAIL
EVA_USERNAME = 'scality_eva'
EVA_EMAIL = 'eva.scality@gmail.com'


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
        assert cls.args.your_login in wall_e.RELEASE_ENGINEERS
        client = Client(cls.args.your_login,
                        cls.args.your_password,
                        cls.args.your_mail)
        cls.bbrepo = BitbucketRepository(client,
                                         owner='scality',
                                         repo_slug=('%s_%s'
                                                    % (cls.args.repo_prefix,
                                                       cls.args.your_login)),
                                         is_private=True,
                                         scm='git')
        try:
            cls.bbrepo.delete()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

        cls.bbrepo.create()

        # Use Eva as our unprivileged user
        assert EVA_USERNAME not in wall_e.RELEASE_ENGINEERS
        client_eva = Client(EVA_USERNAME,
                            cls.args.eva_password,
                            EVA_EMAIL)
        cls.bbrepo_eva = BitbucketRepository(
            client_eva,
            owner='scality',
            repo_slug=('%s_%s' % (cls.args.repo_prefix,
                                  cls.args.your_login)),
        )
        # Wall-E may want to comment manually too
        client_wall_e = Client(WALL_E_USERNAME,
                               cls.args.wall_e_password,
                               WALL_E_EMAIL)
        cls.bbrepo_wall_e = BitbucketRepository(
            client_wall_e,
            owner='scality',
            repo_slug=('%s_%s' % (cls.args.repo_prefix,
                                  cls.args.your_login)),
        )
        cls.gitrepo = GitRepository(cls.bbrepo.get_git_url())
        initialize_git_repo(cls.gitrepo)

    def create_pr(
            self,
            feature_branch,
            from_branch,
            reviewers=[WALL_E_USERNAME],
            file_=True):

        create_branch(feature_branch, from_branch=from_branch, file_=file_)
        pr = self.bbrepo_eva.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': feature_branch}},
            destination={'branch': {'name': from_branch}},
            close_source_branch=True,
            reviewers=[{'username': WALL_E_USERNAME}],
            description=''
        )
        with self.assertRaises(InitMessage):
            self.handle(pr['id'])
        return pr

    def handle(self,
               pull_request_id,
               bypass_peer_approval=False,
               bypass_author_approval=False,
               bypass_jira_version_check=False,
               bypass_jira_type_check=False,
               bypass_build_status=False,
               reference_git_repo='',
               no_comment=False,
               interactive=False):

        sys.argv = ["wall-e.py"]
        if bypass_author_approval:
            sys.argv.append('--bypass-author-approval')
        if bypass_peer_approval:
            sys.argv.append('--bypass-peer-approval')
        if bypass_jira_version_check:
            sys.argv.append('--bypass-jira-version-check')
        if bypass_jira_type_check:
            sys.argv.append('--bypass-jira-type-check')
        if bypass_build_status:
            sys.argv.append('--bypass-build-status')
        if no_comment:
            sys.argv.append('--no-comment')
        if interactive:
            sys.argv.append('--interactive')

        sys.argv.append('--slug')
        sys.argv.append(self.bbrepo['repo_slug'])
        sys.argv.append(str(pull_request_id))
        sys.argv.append(self.args.wall_e_password)
        wall_e.main()

    def test_bugfix_full_merge_manual(self):
        pr = self.create_pr('bugfix/RING-0001', 'development/4.3')
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        # PeerApprovalRequired and AuthorApprovalRequired
        # have the same message, so CommentAlreadyExists is used
        with self.assertRaises(CommentAlreadyExists):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_bugfix_full_merge_automatic(self):
        pr = self.create_pr('bugfix/RING-0002', 'development/4.3')
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_handle_automatically_twice(self):
        pr = self.create_pr('bugfix/RING-0003', 'development/4.3')
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)
        with self.assertRaises(NothingToDo):
            self.handle(pr['id'],
                        bypass_author_approval=True,
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_refuse_feature_on_maintenance_branch(self):
        pr = self.create_pr('feature/RING-0004', 'development/4.3')
        with self.assertRaises(BranchDoesNotAcceptFeatures):
            self.handle(pr['id'],
                        bypass_author_approval=True,
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_branch_name_invalid(self):
        dst_branch = 'feature/RING-0005'
        src_branch = 'user/4.3/RING-0005'
        with self.assertRaises(BranchNameInvalid):
            wall_e.DestinationBranch(dst_branch)
            wall_e.FeatureBranch(src_branch)

    def test_conflict(self):
        pr1 = self.create_pr('bugfix/RING-0006', 'development/4.3',
                             file_='toto.txt')
        pr2 = self.create_pr('improvement/RING-0006', 'development/4.3',
                             file_='toto.txt')
        self.handle(pr1['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)
        with self.assertRaises(Conflict):
            self.handle(pr2['id'],
                        bypass_author_approval=True,
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_approval(self):
        """Test approvals of author and reviewer

        1. Test approval of author
        2. Test approval of reviewer
        """
        feature_branch = 'bugfix/RING-0007'
        dst_branch = 'development/4.3'
        reviewers = ['scality_wall-e']

        pr = self.create_pr(feature_branch, dst_branch, reviewers=reviewers)

        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

        # Author
        pr.approve()

        # PeerApprovalRequired and AuthorApprovalRequired
        # have the same message, so CommentAlreadyExists is used
        with self.assertRaises(CommentAlreadyExists):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        # Reviewer
        client = Client(WALL_E_USERNAME,
                        self.args.wall_e_password,
                        WALL_E_EMAIL)
        w_pr = PullRequest(client, **pr._json_data)
        w_pr.approve()

        self.handle(w_pr['id'],
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_branches_creation_main_pr_not_approved(self):
        """Test if Wall-e creates integration pull-requests when the main
        pull-request isn't approved

        1. Create feature branch and create an unapproved pull request
        2. Run wall-e on the pull request
        3. Check existence of integration branches
        """
        feature_branch = 'bugfix/RING-0008'
        dst_branch = 'development/4.3'
        reviewers = ['scality_wall-e']
        pr = self.create_pr(feature_branch, dst_branch, reviewers=reviewers)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

        # check existence of integration branches
        for version in ['4.3', '5.1', '6.0']:
            remote = 'w/%s/%s' % (version, feature_branch)
            ret = self.gitrepo.remote_branch_exists(remote)
            self.assertTrue(ret)

        # check absence of a missing branch
        self.assertFalse(self.gitrepo.remote_branch_exists('missing_branch'))

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
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00045', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        self.handle(pr['id'])

    def test_bypass_all_approvals_through_bitbucket_comment_extra_spaces(self):
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00046', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('  @%s  '
                             '   bypass_author_approval  '
                             '     bypass_peer_approval   '
                             '  bypass_build_status'
                             '   bypass_jira_version_check'
                             '   bypass_jira_type_check   ' % WALL_E_USERNAME)
        self.handle(pr['id'])

    def test_bypass_all_approvals_through_an_incorrect_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00047', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_aproval'  # a p is missing
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_bypass_all_approvals_through_unauthorized_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00048', 'development/4.3')
        pr.add_comment('@%s'  # comment is made by unpriviledged Eva
                       ' bypass_author_approval'
                       ' bypass_peer_approval'
                       ' bypass_build_status'
                       ' bypass_jira_version_check'
                       ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_bypass_all_approvals_through_an_unknown_bitbucket_comment(self):
        pr = self.create_pr('bugfix/RING-00049', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' mmm_never_seen_that_before'  # this is unknown
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_bypass_all_approvals_through_many_comments(self):
        pr = self.create_pr('bugfix/RING-00050', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s bypass_author_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_peer_approval' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_build_status' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_jira_version_check' % WALL_E_USERNAME)
        pr_admin.add_comment('@%s bypass_jira_type_check' % WALL_E_USERNAME)
        self.handle(pr['id'])

    def test_bypass_all_approvals_through_mix_comments_and_cmdline(self):
        pr = self.create_pr('bugfix/RING-00051', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_build_status=True,
                    bypass_jira_version_check=True)

    def test_bypass_author_approval_through_comment(self):
        pr = self.create_pr('bugfix/RING-00052', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_bypass_peer_approval_through_comment(self):
        pr = self.create_pr('bugfix/RING-00053', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_peer_approval' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_bypass_jira_version_check_through_comment(self):
        pr = self.create_pr('bugfix/RING-00054', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_jira_version_check' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_bypass_jira_type_check_through_comment(self):
        pr = self.create_pr('bugfix/RING-00055', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_build_status=True)

    def test_bypass_build_status_through_comment(self):
        pr = self.create_pr('bugfix/RING-00056', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s'
                             ' bypass_build_status' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True)

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
        self.handle(pr['id'])

    def test_incorrect_address_when_setting_options_through_comments(self):
        pr = self.create_pr('bugfix/RING-00058', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@toto'  # toto is not Wall-E
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check')
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_options_set_through_deleted_comment(self):
        pr = self.create_pr('bugfix/RING-00059', 'development/4.3')
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        comment = pr_admin.add_comment(
            '@%s'
            ' bypass_author_approval'
            ' bypass_peer_approval'
            ' bypass_build_status'
            ' bypass_jira_version_check'
            ' bypass_jira_type_check' % WALL_E_USERNAME
        )
        comment.delete()
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_bypass_all_approvals_through_bitbucket_comment_extra_chars(self):
        # normal user creates the PR
        pr = self.create_pr('bugfix/RING-00060', 'development/4.3')
        # and priviledged user gets it back
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id'])
        pr_admin.add_comment('@%s:'
                             'bypass_author_approval,  '
                             '     bypass_peer_approval,,   '
                             '  bypass_build_status-bypass_jira_version_check'
                             '   bypass_jira_type_check -   ' % WALL_E_USERNAME)
        self.handle(pr['id'])

    def test_help_command(self):
        pr = self.create_pr('bugfix/RING-00061', 'development/4.3')
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'])

    def test_help_command_with_inter_comment(self):
        pr = self.create_pr('bugfix/RING-00062', 'development/4.3')
        pr.add_comment('@%s: help' % WALL_E_USERNAME)
        pr.add_comment('an irrelevant comment')
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'])

    def test_help_command_with_inter_comment_from_wall_e(self):
        pr = self.create_pr('bugfix/RING-00063', 'development/4.3')
        pr.add_comment('@%s help' % WALL_E_USERNAME)
        pr_wall_e = self.bbrepo_wall_e.get_pull_request(pull_request_id=pr['id'])
        pr_wall_e.add_comment('this is my help already')
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_unknown_command(self):
        pr = self.create_pr('bugfix/RING-00064', 'development/4.3')
        pr.add_comment('@%s helpp' % WALL_E_USERNAME)
        self.handle(pr['id'],
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_command_args(self):
        pr = self.create_pr('bugfix/RING-00065', 'development/4.3')
        pr.add_comment('@%s help some arguments --hehe' % WALL_E_USERNAME)
        with self.assertRaises(HelpMessage):
            self.handle(pr['id'])

    def test_main_pr_retrieval(self):
        pr = self.create_pr('bugfix/RING-00066', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        # simulate a child pr update
        self.handle(pr['id']+1,
                    bypass_author_approval=True,
                    bypass_peer_approval=True,
                    bypass_jira_version_check=True,
                    bypass_jira_type_check=True,
                    bypass_build_status=True)

    def test_no_effect_sub_pr_approval(self):
        pr = self.create_pr('bugfix/RING-00067', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        pr_child = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        pr_child.approve()
        with self.assertRaises(CommentAlreadyExists):
            self.handle(pr['id']+1,
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_no_effect_sub_pr_options(self):
        pr = self.create_pr('bugfix/RING-00068', 'development/4.3')
        # create integration PRs first:
        with self.assertRaises(AuthorApprovalRequired):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)
        pr_admin = self.bbrepo.get_pull_request(pull_request_id=pr['id']+1)
        pr_admin.add_comment('@%s'
                             ' bypass_author_approval'
                             ' bypass_peer_approval'
                             ' bypass_build_status'
                             ' bypass_jira_version_check'
                             ' bypass_jira_type_check' % WALL_E_USERNAME)
        with self.assertRaises(CommentAlreadyExists):
            self.handle(pr['id'],
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_child_pr_without_parent(self):
        # simulate creation of an integration branch with Wall-E
        create_branch('w/bugfix/RING-00069', from_branch='development/4.3', file_=True)
        pr = self.bbrepo_wall_e.create_pull_request(
            title='title',
            name='name',
            source={'branch': {'name': 'w/bugfix/RING-00069'}},
            destination={'branch': {'name': 'development/4.3'}},
            close_source_branch=True,
            reviewers=[{'username': EVA_USERNAME}],
            description=''
        )
        with self.assertRaises(ParentNotFound):
            self.handle(pr['id'],
                        bypass_author_approval=True,
                        bypass_peer_approval=True,
                        bypass_jira_version_check=True,
                        bypass_jira_type_check=True,
                        bypass_build_status=True)

    def test_status_command(self):
        pr = self.create_pr('bugfix/RING-00070', 'development/4.3')
        pr.add_comment('@%s status' % WALL_E_USERNAME)

        with self.assertRaises(StatusReport):
            self.handle(pr['id'])

        pr.add_comment('@%s unanimity' % WALL_E_USERNAME)

        pr.add_comment('@%s status' % WALL_E_USERNAME)

        with self.assertRaises(StatusReport):
            self.handle(pr['id'])

    def test_wait_option(self):
        pr = self.create_pr('bugfix/RING-00071', 'development/4.3')
        pr.add_comment('@%s wait' % WALL_E_USERNAME)

        with self.assertRaises(NothingToDo):
            self.handle(pr['id'])


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
    unittest.main(failfast=True, testLoader=loader)


if __name__ == '__main__':
    main()
