#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from wall_e_exceptions import *
from bitbucket_api import BitbucketPullRequest, get_bitbucket_client, create_pullrequest_comment
from collections import OrderedDict
import subprocess
from cmd import cmd
from tempfile import mkdtemp
from urllib import quote

KNOWN_VERSIONS = OrderedDict([
    ('4.3', '4.3.17'),
    ('5.1', '5.1.4'),
    ('6.0', '6.0.0'),
    ('trunk', None)])


class Branch:
    def merge_from(self, source_branch):
        source_branch.checkout()
        self.checkout()
        try:
            cmd('git merge --no-edit %s' % (source_branch.name))  # <- May fail if conflict
        except subprocess.CalledProcessError:
            raise MergeFailedException(self.name, source_branch.name)

    def exists(self):
        try:
            self.checkout()
            return True
        except:
            return False

    def checkout(self):
        cmd('git checkout ' + self.name)

    def push(self):
        self.checkout()
        cmd('git push --set-upstream origin ' + self.name)

    def create_from(self, source_branch):
        source_branch.checkout()
        cmd('git checkout -b ' + self.name)
        self.push()

    def update_or_create_and_merge(self, source_branch, push=True):
        if self.exists():
            self.merge_from(source_branch)
        else:
            self.create_from(source_branch)
        self.push()


class DestinationBranch(Branch):
    def __init__(self, name):
        self.name = name
        assert '/' in name
        self.prefix, self.version = name.split('/', 1)
        assert self.prefix == 'development'
        assert self.version in KNOWN_VERSIONS.keys()


class FeatureBranch(Branch):
    def __init__(self, name):
        self.name = name
        assert '/' in name
        self.prefix, self.subname = name.split('/', 1)
        assert self.prefix in ['feature', 'bugfix', 'improvement']

    def merge_cascade(self, destination_branch):
        if destination_branch.prefix != 'development':
            raise NotMyJobException(self.name, destination_branch.name)
        if self.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(self.name)
        if self.prefix == 'feature' and destination_branch.version in ['4.3', '5.1']:
            raise BranchDoesNotAcceptFeaturesException(destination_branch.name)

        previous_feature_branch = self
        new_pull_requests = []
        for version in KNOWN_VERSIONS.keys():
            if version < destination_branch.version:
                continue
            integration_branch = FeatureBranch('%s/%s/%s' % (self.prefix, version, self.subname))
            integration_branch.update_or_create_and_merge(previous_feature_branch)
            development_branch = DestinationBranch('development/' + version)
            integration_branch.merge_from(development_branch)
            new_pull_requests.append((integration_branch, development_branch))
            previous_feature_branch = integration_branch
        return new_pull_requests


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail):
        self._bbconn = get_bitbucket_client(bitbucket_login, bitbucket_password, bitbucket_mail)
        self.original_pr = None

    def send_bitbucket_msg(self, pull_request_id, msg):
        print('SENDING MSG %s : %s' % (pull_request_id, msg))
        if self.original_pr:
            create_pullrequest_comment(self._bbconn, self.repo_full_name, self.original_pr.id, msg)

    def _handle_pull_request(self,
                             repo_owner,
                             repo_slug,
                             pull_request_id,
                             bypass_peer_approval=False,
                             bypass_author_approval=False,
                             reference_git_repo=''):
        self.repo_full_name = repo_owner + '/' + repo_slug
        self.original_pr = BitbucketPullRequest.find_pullrequest_in_repository_by_id(repo_owner, repo_slug,
                                                                                     pull_request_id,
                                                                                     client=self._bbconn)
        author = self.original_pr.author['username']
        if self.original_pr.state != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDoException('The pull-request\'s state is "%s"' % self.original_pr.state)

        # TODO: Check the size of the diff and issue warnings

        # TODO: Check the feature branch has been rebased

        # TODO: Check jira issue fixedVersion

        # TODO: Check jira issue status

        # TODO: Check build status

        # TODO: make it idempotent


        tmpdir = mkdtemp('git_ring_')
        os.chdir(tmpdir)

        if reference_git_repo:
            reference_git_repo = '--reference %s'%reference_git_repo

        cmd('git clone %s https://%s:%s@bitbucket.org/%s/%s.git' %
                (reference_git_repo, quote(self._bbconn.config.user),
                quote(self._bbconn.config.password), repo_owner, repo_slug))

        os.chdir(repo_slug)

        try:
            source_branch = FeatureBranch(self.original_pr.source['branch']['name'])
            destination_branch = DestinationBranch(self.original_pr.destination['branch']['name'])
        except AssertionError:
            raise NotMyJobException(self.original_pr.source['branch']['name'],
                                    self.original_pr.destination['branch']['name'])

        new_pull_requests = source_branch.merge_cascade(destination_branch)

        original_pr_is_approved_by_author = bypass_author_approval
        original_pr_is_approved_by_peer = bypass_peer_approval
        for participant in self.original_pr.participants:
            if not participant['approved']:
                continue
            if participant['user']['username'] == author:
                original_pr_is_approved_by_author = True
            else:
                original_pr_is_approved_by_peer = True

        all_child_prs_approved_by_author = True
        all_child_prs_approved_by_peer = True

        # TODO : Add build status

        prs = []
        for source_branch, destination_branch in new_pull_requests:
            description = 'This pull-request has been created automatically by @scality_wall-e.\n\n'
            description += 'It is linked to its parent pull request #%s.\n\n' % self.original_pr.id
            description += 'Please do not edit the contents nor the title!\n\n'
            description += 'The only actions allowed are "Approve" or "Comment"!\n\n'
            description += 'You may want to refactor the branch `%s` manually :\n\n' % source_branch.name
            description += '```\n'
            description += '#!bash\n'
            description += '$ git checkout %s\n' % source_branch.name
            description += '$ git pull\n'
            description += '$ # do interesting stuff\n'
            description += '$ git push\n'
            description += '```\n'
            pr_id = BitbucketPullRequest.create(self._bbconn, self.repo_full_name, source_branch.name,
                                                destination_branch.name, reviewers=[],
                                                title='[child] ' + self.original_pr.title,
                                                description=description)
            pr = BitbucketPullRequest.find_pullrequest_in_repository_by_id(repo_owner, repo_slug, pr_id,
                                                                           client=self._bbconn)
            prs.append(pr)
            if original_pr_is_approved_by_author and original_pr_is_approved_by_peer:
                continue

            approved_by_author = original_pr_is_approved_by_author
            approved_by_peer = original_pr_is_approved_by_peer
            for participant in pr.participants:
                if not participant['approved']:
                    continue
                if participant['user']['username'] == author:
                    approved_by_author = True
                else:
                    approved_by_peer = True

            if not approved_by_author:
                all_child_prs_approved_by_author = False


            if not approved_by_peer:
                all_child_prs_approved_by_peer = False

        if not all_child_prs_approved_by_author:
            raise AuthorApprovalRequiredException(prs)

        if not all_child_prs_approved_by_peer:
            raise PeerApprovalRequiredException(prs)


        for pr in prs:
            pr.merge(json={
                'owner': repo_owner,
                'repo_slug': repo_slug,
                'pull_request_id': pr.id
            })

    def handle_pull_request(self,
                            repo_owner,
                            repo_slug,
                            pull_request_id,
                            bypass_peer_approval=False,
                            bypass_author_approval=False,
                            reference_git_repo=''):
        # TODO : This method should be a decorator instead
        try:
            self._handle_pull_request(repo_owner, repo_slug, pull_request_id, bypass_peer_approval, bypass_author_approval)
        except WallE_Exception, e:
            self.send_bitbucket_msg(pull_request_id, e.message)
            raise e


import argparse
def main():
    parser = argparse.ArgumentParser(description='Merges bitbucket pull requests.')
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
    parser.add_argument('--reference_git_repo', default='',
                   help='Reference to a local version of the git repo to improve cloning delay')

    args = parser.parse_args()
    wall_e = WallE('scality_wall-e', args.password, 'wall_e@scality.com')
    wall_e.handle_pull_request(
            repo_owner=args.owner,
            repo_slug=args.slug,
            pull_request_id=args.pullrequest,
            bypass_author_approval=args.bypass_author_approval,
            bypass_peer_approval=args.bypass_peer_approval,
            reference_git_repo=args.reference_git_repo
    )

if __name__ == '__main__':
    main()



