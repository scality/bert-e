#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
from collections import OrderedDict
import re

from template_loader import render
import requests

from bitbucket_api import (Repository as BitBucketRepository,
                           Client)
from git_api import Repository as GitRepository, Branch, MergeFailedException
from jira_api import JiraIssue
from wall_e_exceptions import (NotMyJobException,
                               PrefixCannotBeMergedException,
                               BranchDoesNotAcceptFeaturesException,
                               BranchNameInvalidException,
                               ConflictException,
                               CommentAlreadyExistsException,
                               NothingToDoException,
                               AuthorApprovalRequiredException,
                               PeerApprovalRequiredException,
                               BuildFailedException,
                               BuildNotStartedException,
                               BuildInProgressException,
                               WallE_Exception,
                               WallE_InternalException,
                               WallE_TemplateException)

KNOWN_VERSIONS = OrderedDict([
    ('4.3', '4.3.18'),
    ('5.1', '5.1.4'),
    ('6.0', '6.0.0')])

JIRA_ISSUE_BRANCH_PREFIX = {
    'Epic': 'project',
    'Story': 'feature',
    'Bug': 'bugfix',
    'Improvement': 'improvement'}

WALL_E_USERNAME = 'scality_wall-e'

def confirm(question):
    input_ = raw_input(question + " Enter (y)es or (n)o: ")
    return input_ == "yes" or input_ == "y"


class ScalBranch(Branch):
    def __init__(self, name):
        Branch.__init__(self, name)
        if '/' not in name:
            raise BranchNameInvalidException(name)


class DestinationBranch(ScalBranch):
    def __init__(self, name):
        ScalBranch.__init__(self, name)
        self.prefix, self.version = name.split('/', 1)
        if (self.prefix != 'development' or
                self.version not in KNOWN_VERSIONS.keys()):
            raise BranchNameInvalidException(name)

        self.impacted_versions = OrderedDict(
            [(version, release) for (version, release) in
                KNOWN_VERSIONS.items()
                if version >= self.version])


class FeatureBranch(ScalBranch):
    def __init__(self, name):
        ScalBranch.__init__(self, name)
        self.prefix, self.subname = name.split('/', 1)
        self.jira_issue_id = None
        match = re.match('(?P<issue_id>[A-Z]+-\d+).*', self.subname)
        if match:
            self.jira_issue_id = match.group('issue_id')
        else:
            print('Warning : %s does not contain a correct '
                  'issue id number' % self.name)
            # Fixme : send a comment instead ? or ignore the jira checks ?

    def merge_cascade(self, destination_branch):
        if self.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(source=self,
                                                destination=destination_branch)
        if (self.prefix == 'feature' and
                destination_branch.version in ['4.3', '5.1']):
            raise BranchDoesNotAcceptFeaturesException(
                source=self,
                destination=destination_branch)

        previous_feature_branch = self
        new_pull_requests = []
        for version in destination_branch.impacted_versions:
            integration_branch = (FeatureBranch('w/%s/%s/%s'
                                  % (version, self.prefix, self.subname)))
            try:
                (integration_branch
                 .update_or_create_and_merge(previous_feature_branch))
            except MergeFailedException:
                raise ConflictException(source=integration_branch,
                                        destination=previous_feature_branch)
            development_branch = DestinationBranch('development/' + version)
            try:
                integration_branch.merge(development_branch)
            except MergeFailedException:
                raise ConflictException(source=integration_branch,
                                        destination=development_branch)
            integration_branch.push()
            new_pull_requests.append((integration_branch, development_branch))
            previous_feature_branch = integration_branch
        return new_pull_requests


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail):
        self._bbconn = Client(bitbucket_login,
                              bitbucket_password, bitbucket_mail)
        self.original_pr = None

    def check_build_status(self, pr, key):
        try:
            build_state = self.bbrepo.get_build_status(
                revision=pr['source']['commit']['hash'],
                key=key
            )['state']
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise BuildNotStartedException(pr['id'])
            raise
        else:
            if build_state == 'FAILED':
                raise BuildFailedException(pr['id'])
            elif build_state == 'INPROGRESS':
                raise BuildInProgressException(pr['id'])

            assert build_state == 'SUCCESSFUL'

    def send_bitbucket_msg(self, pull_request_id, msg, no_comment=False,
                           interactive=False):
        print('SENDING MSG %s : %s' % (pull_request_id, msg))
        if not self.original_pr:
            return
        # the last comment is the first
        for index, comment in enumerate(self.original_pr.get_comments()):
            if (comment['user']['username'] == WALL_E_USERNAME and
                    comment['content']['raw'] == msg):
                raise CommentAlreadyExistsException('The same comment has '
                                                    'already been posted by '
                                                    'Wall-E in the past. '
                                                    'Nothing to do here!')
            elif index > 10:
                # if wall-e doesn't do anything in the last 10 comments,
                # allow him to run again
                break
        if no_comment:
            return
        if interactive and not confirm('Do you want to send this comment ?'):
            return
        self.original_pr.add_comment(msg)

    def jira_checks(self, source_branch, destination_branch,
                    bypass_jira_version_check, bypass_jira_type_check):
        """performs checks using the Jira issue id specified in the source
        branch name"""
        if bypass_jira_version_check and bypass_jira_type_check:
            return

        if not source_branch.jira_issue_id:
            if destination_branch.version in ['6.0', 'trunk']:
                # We do not want to merge in maintenance branches without
                # proper ticket handling but it is OK for future releases.
                # FIXME : versions should not be hardcoded
                return

            raise WallE_Exception('You want to merge `%s` into a maintenance '
                                  'branch but this branch does not specify a '
                                  'Jira issue id' % (source_branch.name))

        issue = JiraIssue(issue_id=source_branch.jira_issue_id,
                          login='wall_e',
                          passwd=self._bbconn.auth.password)

        # Use parent task instead
        if issue.fields.issuetype.name == 'Sub-task':
            issue = JiraIssue(issue_id=issue.fields.parent.key,
                              login='wall_e',
                              passwd=self._bbconn.auth.password)

        # Fixme : add proper error handling
        # What happens when the issue does not exist ? -> comment on PR ?
        # What happens in case of network failure ? -> fail silently ?
        # What else can happen ?
        if not bypass_jira_type_check:
            issuetype = issue.fields.issuetype.name
            expected_prefix = JIRA_ISSUE_BRANCH_PREFIX.get(issuetype)
            if expected_prefix is None:
                raise WallE_InternalException('Jira issue: unknow type %r' %
                                              issuetype)
            if expected_prefix != source_branch.prefix:
                raise WallE_Exception('branch prefix name %r mismatches '
                                      'jira issue type field %r' %
                                      (source_branch.prefix, expected_prefix))

        if not bypass_jira_version_check:
            issue_versions = set([version.name for version in
                                  issue.fields.fixVersions])
            expect_versions = set(
                destination_branch.impacted_versions.values())
            if issue_versions != expect_versions:
                raise WallE_Exception("The issue 'Fix Version/s' field "
                                      "contains %s. It must contain: %s." %
                                      (', '.join(issue_versions),
                                       ', '.join(expect_versions)))

    def _handle_pull_request(self,
                             owner,
                             repo_slug,
                             pull_request_id,
                             bypass_peer_approval=False,
                             bypass_author_approval=False,
                             bypass_jira_version_check=False,
                             bypass_jira_type_check=False,
                             bypass_build_status=False,
                             reference_git_repo='',
                             no_comment=False,
                             interactive=False):

        self.bbrepo = BitBucketRepository(self._bbconn, owner=owner,
                                          repo_slug=repo_slug)
        self.repo_full_name = owner + '/' + repo_slug
        self.original_pr = (self.bbrepo
                            .get_pull_request(pull_request_id=pull_request_id))
        if self.original_pr['state'] != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDoException('The pull-request\'s state is "%s"'
                                       % self.original_pr['state'])

        # TODO: Check the size of the diff and issue warnings

        # TODO: Check build status

        # TODO: make it idempotent

        dst_brnch_name = self.original_pr['destination']['branch']['name']
        src_brnch_name = self.original_pr['source']['branch']['name']
        try:
            destination_branch = DestinationBranch(dst_brnch_name)
        except BranchNameInvalidException as e:
            print('Destination branch %r not handled, ignore PR %s'
                  % (e.branch, pull_request_id))
            # Nothing to do
            raise NotMyJobException(src_brnch_name, dst_brnch_name)

        try:
            source_branch = FeatureBranch(
                self.original_pr['source']['branch']['name'])
        except BranchNameInvalidException as e:
            raise PrefixCannotBeMergedException(e.branch)

        if source_branch.prefix == 'hotfix':
            # hotfix branches are ignored, nothing todo
            print("Ignore branch %r" % source_branch.name)
            return

        if source_branch.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(source_branch.name)

        self.jira_checks(source_branch, destination_branch,
                         bypass_jira_version_check, bypass_jira_type_check)

        git_repo = GitRepository(self.bbrepo.get_git_url())
        git_repo.clone(reference_git_repo)

        git_repo.config('user.email', '"%s"'
                        % self._bbconn.mail)
        git_repo.config('user.name', '"Wall-E"')

        new_pull_requests = source_branch.merge_cascade(destination_branch)

        # Create integration PR
        child_prs = []
        author = self.original_pr['author']['username']
        for source_branch, destination_branch in new_pull_requests:
            title = ('[%s] #%s: %s'
                     % (destination_branch.name,
                        pull_request_id, self.original_pr['title']))

            description = render('pull_request_description.md',
                                 pr=self.original_pr)
            pr = (self.bbrepo
                  .create_pull_request(title=title,
                                       name='name',
                                       source={'branch':
                                               {'name':
                                                source_branch.name}},
                                       destination={'branch':
                                                    {'name':
                                                     destination_branch
                                                     .name}},
                                       close_source_branch=True,
                                       reviewers=[{'username': author}],
                                       description=description))
            child_prs.append(pr)

        # Check parent PR: approval
        self.check_approval(bypass_author_approval, bypass_peer_approval,
                            child_prs)

        # Check integration PR: build status
        for pr in child_prs:
            if not bypass_build_status:
                self.check_build_status(pr, 'jenkins_build')
                self.check_build_status(pr, 'jenkins_utest')

        if interactive and not confirm('Do you want to merge ?'):
            return

        for pr in child_prs:
            pr.merge()

    def check_approval(self, bypass_author_approval, bypass_peer_approval,
                       child_prs):
        original_pr_is_approved_by_author = bypass_author_approval
        original_pr_is_approved_by_peer = bypass_peer_approval

        # NB: when author hasn't approved the PR, author isn't listed in
        # 'participants'
        for participant in self.original_pr['participants']:
            if not participant['approved']:
                continue
            author = self.original_pr['author']['username']
            if participant['user']['username'] == author:
                original_pr_is_approved_by_author = True
            else:
                original_pr_is_approved_by_peer = True

        if not original_pr_is_approved_by_author:
            raise AuthorApprovalRequiredException(pr=self.original_pr,
                                                  child_prs=child_prs)

        if not original_pr_is_approved_by_peer:
            raise PeerApprovalRequiredException(pr=self.original_pr,
                                                child_prs=child_prs)

    def handle_pull_request(self,
                            repo_owner,
                            repo_slug,
                            pull_request_id,
                            bypass_peer_approval=False,
                            bypass_author_approval=False,
                            bypass_jira_version_check=False,
                            bypass_jira_type_check=False,
                            bypass_build_status=False,
                            reference_git_repo='',
                            no_comment=False,
                            interactive=False):
        # TODO : This method should be a decorator instead
        try:
            self._handle_pull_request(repo_owner,
                                      repo_slug,
                                      pull_request_id,
                                      bypass_peer_approval,
                                      bypass_author_approval,
                                      bypass_jira_version_check,
                                      bypass_jira_type_check,
                                      bypass_build_status,
                                      reference_git_repo,
                                      no_comment,
                                      interactive)
        except (WallE_Exception, WallE_TemplateException) as e:
            self.send_bitbucket_msg(pull_request_id, str(e),
                                    no_comment=no_comment,
                                    interactive=interactive)
            raise


def main():
    parser = (argparse
              .ArgumentParser(description='Merges bitbucket pull requests.'))
    parser.add_argument('pullrequest',
                        help='The ID of the pull request')
    parser.add_argument('password',
                        help='Wall-E\'s password [for Jira and Bitbucket]')
    parser.add_argument('--owner', default='scality',
                        help='The owner of the repo (default: scality)')
    parser.add_argument('--slug', default='ring',
                        help='The repo\'s slug (default: ring)')
    parser.add_argument('--bypass_author_approval', action='store_true',
                        help='Bypass the pull request author\'s approval')
    parser.add_argument('--bypass_peer_approval', action='store_true',
                        help='Bypass the pull request peer\'s approval')
    parser.add_argument('--bypass_jira_version_check', action='store_true',
                        help='Bypass the Jira fixVersions field check')
    parser.add_argument('--bypass_jira_type_check', action='store_true',
                        help='Bypass the Jira issueType field check')
    parser.add_argument('--bypass_build_status', action='store_true',
                        help='Bypass the build and test status')
    parser.add_argument('--reference_git_repo', default='',
                        help='Reference to a local version of the git repo '
                             'to improve cloning delay')
    parser.add_argument('--no_comment', action='store_true',
                        help='Do not add any comment to the pull request page')
    parser.add_argument('--interactive', action='store_true',
                        help='Ask before merging or sending comments')

    args = parser.parse_args()

    wall_e = WallE(WALL_E_USERNAME, args.password, 'wall_e@scality.com')
    wall_e.handle_pull_request(repo_owner=args.owner,
                               repo_slug=args.slug,
                               pull_request_id=args.pullrequest,
                               bypass_author_approval=args.
                               bypass_author_approval,
                               bypass_peer_approval=args.bypass_peer_approval,
                               bypass_jira_version_check=args.
                               bypass_jira_version_check,
                               bypass_jira_type_check=args.
                               bypass_jira_type_check,
                               bypass_build_status=args.bypass_build_status,
                               reference_git_repo=args.reference_git_repo,
                               no_comment=args.no_comment,
                               interactive=args.interactive)

if __name__ == '__main__':
    main()
