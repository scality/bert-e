#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
from collections import OrderedDict

from bitbucket_api import (Repository as BitBucketRepository,
                           get_bitbucket_client)
from git_api import Repository as GitRepository, Branch, MergeFailedException
from wall_e_exceptions import (NotMyJobException,
                               PrefixCannotBeMergedException,
                               BranchDoesNotAcceptFeaturesException,
                               ConflictException,
                               CommentAlreadyExistsException,
                               NothingToDoException,
                               AuthorApprovalRequiredException,
                               PeerApprovalRequiredException,
                               WallE_Exception)


KNOWN_VERSIONS = OrderedDict([
    ('4.3', '4.3.17'),
    ('5.1', '5.1.4'),
    ('6.0', '6.0.0'),
    ('trunk', None)])


class ScalBranch(Branch):
    def __init__(self, name):
        assert '/' in name
        self.name = name


class DestinationBranch(ScalBranch):
    def __init__(self, name):
        super(DestinationBranch, self).__init__(name)
        self.prefix, self.version = name.split('/', 1)
        assert self.prefix == 'development'
        assert self.version in KNOWN_VERSIONS.keys()


class FeatureBranch(ScalBranch):
    def __init__(self, name):
        super(FeatureBranch, self).__init__(name)
        self.prefix, self.subname = name.split('/', 1)

    def merge_cascade(self, destination_branch):
        if destination_branch.prefix != 'development':
            raise NotMyJobException(self.name, destination_branch.name)
        if self.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(self.name)
        if (self.prefix == 'feature' and
                destination_branch.version in ['4.3', '5.1']):
            raise BranchDoesNotAcceptFeaturesException(destination_branch.name)

        previous_feature_branch = self
        new_pull_requests = []
        for version in KNOWN_VERSIONS.keys():
            if version < destination_branch.version:
                continue
            integration_branch = (FeatureBranch('w/%s/%s/%s'
                                  % (version, self.prefix, self.subname)))
            try:
                (integration_branch
                 .update_or_create_and_merge(previous_feature_branch))
            except MergeFailedException:
                raise ConflictException(self, previous_feature_branch)
            development_branch = DestinationBranch('development/' + version)
            try:
                integration_branch.merge(development_branch)
            except MergeFailedException:
                raise ConflictException(self, previous_feature_branch)
            new_pull_requests.append((integration_branch, development_branch))
            previous_feature_branch = integration_branch
        return new_pull_requests


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail):
        self._bbconn = get_bitbucket_client(bitbucket_login,
                                            bitbucket_password, bitbucket_mail)
        self.original_pr = None

    def send_bitbucket_msg(self, pull_request_id, msg):
        print('SENDING MSG %s : %s' % (pull_request_id, msg))
        if not self.original_pr:
            return
        # the last comment is the first
        for index, comment in enumerate(self.original_pr.get_comments()):
            if (comment['user']['username'] == 'scality_wall-e' and
                    comment['content']['raw'] == msg):
                raise CommentAlreadyExistsException('The same comment has '
                                                    'already been posted by '
                                                    'Wall-E in the past. '
                                                    'Nothing to do here!')
            elif index > 10:
                # if wall-e doesn't do anything in the last 10 comments,
                # allow him to run again
                break
        self.original_pr.add_comment(msg)

    def _handle_pull_request(self,
                             owner,
                             repo_slug,
                             pull_request_id,
                             bypass_peer_approval=False,
                             bypass_author_approval=False,
                             reference_git_repo=''):

        self.bbrepo = BitBucketRepository(self._bbconn, owner=owner,
                                          repo_slug=repo_slug)
        self.repo_full_name = owner + '/' + repo_slug
        self.original_pr = (self.bbrepo
                            .get_pull_request(pull_request_id=pull_request_id))
        author = self.original_pr['author']['username']
        if self.original_pr['state'] != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDoException('The pull-request\'s state is "%s"'
                                       % self.original_pr['state'])

        # TODO: Check the size of the diff and issue warnings

        # TODO: Check the feature branch has been rebased

        # TODO: Check jira issue fixedVersion

        # TODO: Check jira issue status

        # TODO: Check build status

        # TODO: make it idempotent

        git_repo = GitRepository(self.bbrepo.get_git_url())
        git_repo.clone(reference_git_repo)

        git_repo.config('user.email', '"%s"'
                        % self._bbconn.config.client_email)
        git_repo.config('user.name', '"Wall-E"')

        try:
            source_branch = FeatureBranch(self
                                          .original_pr
                                          ['source']['branch']['name'])
            if source_branch.prefix == 'hotfix':
                # hotfix branches are ignored, nothing todo
                print("Ignore branch %r" % source_branch.name)
                return
            assert source_branch.prefix in ['feature', 'bugfix', 'improvement']
            destination_branch = DestinationBranch(self
                                                   .original_pr
                                                   ['destination']['branch']
                                                   ['name'])
        except AssertionError:
            raise NotMyJobException(self
                                    .original_pr['source']['branch']['name'],
                                    self
                                    .original_pr
                                    ['destination']['branch']['name'])

        new_pull_requests = source_branch.merge_cascade(destination_branch)

        original_pr_is_approved_by_author = bypass_author_approval
        original_pr_is_approved_by_peer = bypass_peer_approval
        for participant in self.original_pr['participants']:
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
            title = ('[%s] #%s: %s'
                     % (destination_branch.name,
                        pull_request_id, self.original_pr['title']))
            description = ('This pull-request has been created automatically '
                           'by @scality_wall-e.\n\n'
                           'It is linked to its parent pull request #%s.\n\n'
                           'Please do not edit the contents nor the title!\n\n'
                           'The only actions allowed are '
                           '"Approve" or "Comment"!\n\n'
                           'You may want to refactor the branch '
                           '`%s` manually :\n\n'
                           '```\n'
                           '#!bash\n'
                           '$ git checkout %s\n'
                           '$ git pull\n'
                           '$ # do interesting stuff\n'
                           '$ git push\n'
                           '```\n'
                           % (self.original_pr['id'], source_branch.name,
                              source_branch.name))
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
            prs.append(pr)
            if (original_pr_is_approved_by_author and
                    original_pr_is_approved_by_peer):
                continue

            approved_by_author = original_pr_is_approved_by_author
            approved_by_peer = original_pr_is_approved_by_peer
            for participant in pr['participants']:
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
            pr.merge()

    def handle_pull_request(self,
                            repo_owner,
                            repo_slug,
                            pull_request_id,
                            bypass_peer_approval=False,
                            bypass_author_approval=False,
                            reference_git_repo='',
                            description=''):
        # TODO : This method should be a decorator instead
        try:
            self._handle_pull_request(repo_owner, repo_slug, pull_request_id,
                                      bypass_peer_approval,
                                      bypass_author_approval,
                                      reference_git_repo)
        except WallE_Exception as e:
            self.send_bitbucket_msg(pull_request_id, str(e))
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
    parser.add_argument('--reference_git_repo', default='',
                        help='Reference to a local version of the git repo '
                             'to improve cloning delay')

    args = parser.parse_args()
    wall_e = WallE('scality_wall-e', args.password, 'wall_e@scality.com')
    wall_e.handle_pull_request(repo_owner=args.owner,
                               repo_slug=args.slug,
                               pull_request_id=args.pullrequest,
                               bypass_author_approval=args
                               .bypass_author_approval,
                               bypass_peer_approval=args.bypass_peer_approval,
                               reference_git_repo=args.reference_git_repo)


if __name__ == '__main__':
    main()
