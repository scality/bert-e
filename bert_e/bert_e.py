#!/usr/bin/env python3
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
import itertools
import logging
import re
from collections import OrderedDict, deque
from datetime import datetime
from os.path import exists
from types import SimpleNamespace
from urllib.parse import quote_plus

from .api.git import Repository as GitRepository
from .exceptions import *
from .git_host.factory import client_factory
from .lib.cli import confirm
from .lib.settings_dict import SettingsDict
from .settings import setup_settings
from .workflow import gitwaterflow as gwf
from .workflow.gitwaterflow.branches import *  # Temporary fix for the tests

SHA1_LENGHT = [12, 40]

# This variable is used to get an introspectable status that the server can
# display.
STATUS = {}


LOG = logging.getLogger(__name__)


class BertE:
    def __init__(self, settings):
        self.settings = settings
        self.client = client_factory(
            settings.repository_host,
            settings.robot_username,
            settings.robot_password,
            settings.robot_email
        )
        self.project_repo = self.client.get_repository(
            owner=settings.repository_owner,
            slug=settings.repository_slug
        )
        settings['use_queue'] = not settings.disable_queues
        self.token = None
        self.git_repo = GitRepository(
            self.project_repo.git_url,
            mask_pwd=quote_plus(settings.robot_password)
        )

        # This is a temporary namespace utility.
        # TODO: Create actual job classes.

        self.job = SimpleNamespace(
            pull_request=None,
            project_repo=None,
            git=SimpleNamespace(
                repo=None,
                src_branch=None,
                dst_branch=None,
                cascade=None
            ),
            settings=SettingsDict({}, settings)
        )
        self.tmpdir = self.git_repo.tmp_directory
        gwf.setup({key: True for key in settings.cmd_line_options})

    def handle_token(self, token):
        """Determine the resolution path based on the input id.

        Args:
          - token (str):
            - pull request id: handle the pull request update
            - sha1: analyse state of the queues,
                    only if the sha1 belongs to a queue

        Returns:
            - a Bert-E return code

        """
        self.token = token
        try:
            if len(self.token) in SHA1_LENGHT:
                branches = self.git_repo.get_branches_from_sha1(self.token)
                for branch in branches:
                    if self.settings.use_queue and isinstance(
                            branch_factory(self.git_repo, branch),
                            QueueIntegrationBranch):
                        return self.handle_merge_queues()   # queued

                return self.handle_pull_request_from_sha1(self.token)

            try:
                int(self.token)
            except ValueError:
                pass
            else:
                # it is probably a pull request id
                return self.handle_pull_request(self.token)

            raise UnsupportedTokenType(self.token)

        except SilentException as excp:
            if self.settings.backtrace:
                raise

            logging.info('Exception raised: %d', excp.code)
            if not self.settings.quiet:
                print('%d - %s' % (0, excp.__class__.__name__))
            return 0

    def handle_pull_request(self, pr_id):
        """Entry point to handle a pull request id."""
        job = self.new_job()
        self.initialize_pull_request(job, int(pr_id))

        try:
            gwf.handle_pull_request(job)
        except TemplateException as excp:
            self.send_comment(excp)

            if self.settings.backtrace:
                raise excp

            logging.info('Exception raised: %d %s', excp.code, excp.__class__)
            if not self.settings.quiet:
                print('%d - %s' % (excp.code, excp.__class__.__name__))
            return excp.code

    def handle_pull_request_from_sha1(self, sha1):
        """Entry point to handle a pull request from a sha1."""
        pr = self.get_integration_pull_request_from_sha1(sha1)
        if not pr:
            raise NothingToDo('Could not find the PR corresponding to'
                              ' sha1: %s' % sha1)
        return self.handle_pull_request(pr.id)

    def handle_merge_queues(self):
        """Entry point to handle queues following a build status update."""
        job = self.new_job()
        gwf.queueing.handle_merge_queues(job)

    def get_integration_pull_request_from_sha1(self, sha1):
        """Get the oldest open integration pull request containing given
        commit.

        """
        git_repo = GitRepository(
            self.project_repo.git_url,
            mask_pwd=quote_plus(self.settings.robot_password))
        candidates = [b for b in git_repo.get_branches_from_sha1(sha1)
                      if b.startswith('w/')]
        if not candidates:
            return
        prs = list(
            pr for pr in self.project_repo.get_pull_requests(
                src_branch=candidates,
                author=self.settings['robot_username'])
            if pr.status == 'OPEN'
        )
        if not prs:
            return
        return min(prs, key=lambda pr: pr.id)

    def find_comment(self, username=None, startswith=None, max_history=None):
        # check last commits
        job = self.job
        comments = reversed(job.pull_request.comments)
        if max_history not in (None, -1):
            comments = itertools.islice(comments, 0, max_history)
        for comment in comments:
            u = comment.author
            raw = comment.text
            # python3
            if isinstance(username, str) and u != username:
                continue
            if startswith and not raw.startswith(startswith):
                if max_history == -1:
                    return
                continue
            return comment

    def _send_msg(self, msg, dont_repeat_if_in_history=10):
        if self.settings.no_comment:
            logging.debug('not sending message due to no_comment being True.')
            return

        # Apply no-repeat strategy
        if dont_repeat_if_in_history:
            if self.find_comment(
                    username=self.settings['robot_username'],
                    startswith=msg,
                    max_history=dont_repeat_if_in_history):
                raise CommentAlreadyExists(
                    'The same comment has already been posted '
                    'in the past. Nothing to do here!'
                )

        if self.settings.interactive:
            print('%s\n' % msg)
            if not confirm('Do you want to send this comment?'):
                return

        logging.debug('SENDING MSG %s', msg)
        return self.job.pull_request.add_comment(msg)

    def send_comment(self, msg):
        try:
            return self._send_msg(str(msg), msg.dont_repeat_if_in_history)
        except CommentAlreadyExists:
            logging.info("Comment '%s' already posted", msg.__class__.__name__)

    def new_job(self):
        job = self.job = SimpleNamespace(
            bert_e=self,
            pull_request=None,
            project_repo=None,
            git=SimpleNamespace(
                repo=None,
                src_branch=None,
                dst_branch=None,
                cascade=None
            ),
            settings=SettingsDict({}, self.settings)
        )
        job.project_repo = self.project_repo
        job.git.repo = self.git_repo
        job.git.cascade = BranchCascade()
        return job

    def initialize_pull_request(self, job, pr_id):
        repo = job.project_repo
        pull_request = repo.get_pull_request(pr_id)
        if pull_request.author == self.settings['robot_username']:
            res = re.search('(?P<pr_id>\d+)', pull_request.description)
            if not res:
                raise ParentPullRequestNotFound(pull_request.id)
            pull_request_id = int(res.group('pr_id'))
            pull_request = repo.get_pull_request(pull_request_id)
        job.pull_request = pull_request

    def add_merged_pr(self, pr_id):
        """Add pr_id to the list of merged pull requests.

        This list is an inspectable dequeue containing the last 10 merged pull
        requests' IDs.

        """
        merged_prs = STATUS.setdefault('merged PRs', deque(maxlen=10))
        merged_prs.append({'id': pr_id, 'merge_time': datetime.now()})

    def update_queue_status(self, queue_collection):
        """Set the inspectable merge queue status.

        It consists in an ordereddict on the form:

            {
                PR_ID: [(VERSION, SHA1), (VERSION, SHA1), ...]
                ...
            }

        It is ordered by PR queuing date (the most recently queued PR last).
        The lists are ordered by target version number (the most recent version
        first).

        """
        queues = queue_collection._queues
        qib = QueueIntegrationBranch
        status = OrderedDict()
        # initialize status dict
        for branch in reversed(queues[list(queues.keys())[-1]][qib]):
            status[branch.pr_id] = []
        for version, queue in reversed(queues.items()):
            for branch in queue[qib]:
                status[branch.pr_id].append((version,
                                             branch.get_latest_commit()))
        STATUS['merge queue'] = status


def setup_parser():
    parser = argparse.ArgumentParser(add_help=True,
                                     description='Merges bitbucket '
                                                 'pull requests.')
    parser.add_argument(
        'settings',
        help="Path to project settings file")
    parser.add_argument(
        'robot_password',
        help="Robot Bitbucket/GitHub password")
    parser.add_argument(
        'jira_password',
        help="Robot Jira password")
    parser.add_argument(
        'token', type=str,
        help="The ID of the pull request or sha1 (%s characters) "
             "to analyse" % SHA1_LENGHT)
    parser.add_argument(
        '--disable-queues', action='store_true', default=False,
        help="Deactivate optimistic merge queue (legacy mode)")
    parser.add_argument(
        '--option', '-o', action='append', type=str, dest='cmd_line_options',
        help="Activate additional options")
    parser.add_argument(
        '--interactive', action='store_true', default=False,
        help="Ask before merging or sending comments")
    parser.add_argument(
        '--no-comment', action='store_true', default=False,
        help="Do not add any comment to the pull request page")
    parser.add_argument(
        '-v', action='store_true', dest='verbose', default=False,
        help="Verbose mode")
    parser.add_argument(
        '--backtrace', action='store_true', default=False,
        help="Show backtrace instead of return code on console")
    parser.add_argument(
        '--quiet', action='store_true', default=False,
        help="Don't print return codes on the console")
    return parser


def main():
    parser = setup_parser()
    args = parser.parse_args()
    if not args.cmd_line_options:
        args.cmd_line_options = []

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # request lib is noisy
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.WARNING)
    requests_log.propagate = True

    settings = setup_settings(args.settings)
    settings.update(vars(args))

    bert_e = BertE(settings)

    with bert_e.git_repo:
        return bert_e.handle_token(args.token.strip())

    assert not exists(bert_e.tmpdir), (
        "temporary workdir '%s' wasn't deleted!" % bert_e.tmpdir)


if __name__ == '__main__':
    main()
