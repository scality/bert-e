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

import yaml

from .api.git import Repository as GitRepository
from .exceptions import *
from .git_host import bitbucket
from .utils import SettingsDict, confirm
from .workflow import gitwaterflow as gwf
from .workflow.gitwaterflow.branches import *  # Temporary fix for the tests

SHA1_LENGHT = [12, 40]

DEFAULT_OPTIONAL_SETTINGS = {
    'build_key': 'pre-merge',
    'required_peer_approvals': 2,
    'jira_account_url': '',
    'jira_username': '',
    'jira_keys': [],
    'prefixes': {},
    'testers': [],
    'admins': [],
    'tasks': [],
}

# This variable is used to get an introspectable status that the server can
# display.
STATUS = {}


class BertE:
    def __init__(self, args, settings):
        # FIXME: use abstract API
        self.client = bitbucket.Client(
            settings['robot_username'],
            args.bitbucket_password,
            settings['robot_email']
        )
        self.bbrepo = bitbucket.Repository(
            client=self.client,
            owner=settings['repository_owner'],
            repo_slug=settings['repository_slug']
        )
        self.settings = settings
        settings['jira_password'] = args.jira_password
        self.backtrace = args.backtrace
        self.interactive = settings['interactive'] = args.interactive
        self.no_comment = settings['no_comment'] = args.no_comment
        self.quiet = args.quiet
        self.token = args.token.strip()
        self.use_queue = settings['use_queue'] = not args.disable_queues
        self.repo = GitRepository(self.bbrepo.git_url)
        self.tmpdir = self.repo.tmp_directory

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

    def handler(self):
        """Determine the resolution path based on the input id.

        Args:
          - token (str):
            - pull request id: handle the pull request update
            - sha1: analyse state of the queues,
               only if the sha1 belongs to a queue

        Returns:
            - a Bert-E return code

        """
        try:
            if len(self.token) in SHA1_LENGHT:
                branches = self.repo.get_branches_from_sha1(self.token)
                for branch in branches:
                    if self.use_queue and isinstance(
                            branch_factory(self.repo, branch),
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
            if self.backtrace:
                raise

            logging.info('Exception raised: %d', excp.code)
            if not self.quiet:
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

            if self.backtrace:
                raise excp

            logging.info('Exception raised: %d %s', excp.code, excp.__class__)
            if not self.quiet:
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
        git_repo = GitRepository(self.bbrepo.git_url)
        candidates = [b for b in git_repo.get_branches_from_sha1(sha1)
                      if b.startswith('w/')]
        if not candidates:
            return
        prs = list(self.bbrepo.get_pull_requests(
            src_branch=candidates,
            author=self.settings['robot_username']))
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
        if self.no_comment:
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

        if self.interactive:
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
        job.project_repo = self.bbrepo
        job.git.repo = self.repo
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
        'bitbucket_password',
        help="Robot Bitbucket password")
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


def setup_settings(settings_file):
    settings = dict(DEFAULT_OPTIONAL_SETTINGS)

    if not exists(settings_file):
        raise SettingsFileNotFound(settings_file)

    with open(settings_file, 'r') as f:
        try:
            # read the yaml data as pure string (no conversion)
            new_settings = yaml.load(f, Loader=yaml.BaseLoader)
        except Exception:
            raise IncorrectSettingsFile(settings_file)

    # replace default data by provided data
    for key in new_settings:
        settings[key] = new_settings[key]

    # check settings type and presence
    for setting_ in ['repository_owner', 'repository_slug',
                     'robot_username', 'robot_email', 'build_key',
                     'jira_account_url', 'jira_username',
                     'pull_request_base_url', 'commit_base_url']:
        if setting_ not in settings:
            raise MissingMandatorySetting(settings_file)

        if not isinstance(settings[setting_], str):
            raise IncorrectSettingsFile(settings_file)

    try:
        settings['required_peer_approvals'] = int(
            settings['required_peer_approvals'])
    except ValueError:
        raise IncorrectSettingsFile(settings_file)

    for setting_ in ['prefixes']:
        if not isinstance(settings[setting_], dict):
            raise IncorrectSettingsFile(settings_file)

    for setting_ in ['jira_keys', 'admins', 'tasks']:
        if not isinstance(settings[setting_], list):
            raise IncorrectSettingsFile(settings_file)

        for data in settings[setting_]:
            if not isinstance(data, str):
                raise IncorrectSettingsFile(settings_file)

    return settings


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

    gwf.setup({key: True for key in args.cmd_line_options})
    bert_e = BertE(args, settings)

    try:
        return bert_e.handler()
    finally:
        bert_e.repo.delete()
        assert not exists(bert_e.tmpdir), (
            "temporary workdir '%s' wasn't deleted!" % bert_e.tmpdir)


if __name__ == '__main__':
    main()
