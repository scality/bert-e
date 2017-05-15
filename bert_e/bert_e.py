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
import logging
from collections import OrderedDict, deque
from datetime import datetime
from os.path import exists
from queue import Queue
from urllib.parse import quote_plus

import raven

from .exceptions import (BertE_Exception, InternalException, SilentException,
                         TemplateException, UnsupportedTokenType)
from .git_host import client_factory
from .job import CommitJob, JobDispatcher, PullRequestJob
from .lib.git import Repository as GitRepository
from .settings import setup_settings
from .workflow import gitwaterflow as gwf
from .workflow.gitwaterflow.branches import QueueIntegrationBranch

SHA1_LENGTH = [12, 40]
LOG = logging.getLogger(__name__)


class BertE(JobDispatcher):
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

        if settings.repository_host == 'github':
            # Github doesn't support author approvals nor tasks
            if settings['need_author_approval']:
                LOG.warning("Disabling author_approval on GitHub repo")
                settings['need_author_approval'] = False
            if settings['tasks']:
                LOG.warning("Disabling tasks on GitHub repo")
                settings['tasks'] = []

        self.git_repo = GitRepository(
            self.project_repo.git_url,
            mask_pwd=quote_plus(settings.robot_password)
        )
        self.tmpdir = self.git_repo.tmp_directory
        gwf.setup({key: True for key in settings.cmd_line_options})

        self.task_queue = Queue()
        self.tasks_done = deque(maxlen=1000)
        self.status = {}  # TODO: implement a proper status class
        self.raven_client = raven.Client(settings.sentry_dsn)

    def process_task(self):
        """Pop one task off of the task queue and process it.

        This method is called in an infinite loop and a dedicated thread when
        BertE is being run as a server.

        """
        job = self.status['current job'] = self.task_queue.get()

        try:
            self.process(job)
        except Exception as err:
            job.status = type(err).__name__
            job.details = None

            if not isinstance(err, (BertE_Exception, InternalException)):
                LOG.error("Job %s finished with an error: %s", job, err)
                job.details = str(err)
                self.raven_client.captureException()
        finally:
            job.complete()
            self.task_queue.task_done()
            LOG.info("It took Bert-E %s to handle job %s (%s)",
                     datetime.now() - job.start_time, job, job.status)
            self.tasks_done.appendleft(job)
            self.status.pop('current job')
        return job

    def put_job(self, job):
        """Put a job and ensure there is not any similar job in the
        tasks queue.
        """
        if job not in self.task_queue.queue:
            self.task_queue.put(job)
            LOG.info('Adding job %r', job)
        else:
            LOG.info('Job %r already present in the queue. Skipping.')

    def process(self, job):
        """High-level job-processing method."""
        # The git repo is now a long-running instance, but the implementation
        # can't handle this yet, so we explicitely reset the repo before any
        # new run.
        self.git_repo.reset()
        try:
            return self.dispatch(job)
        except SilentException as err:
            self._process_error(err)
            return 0  # SilentExceptions should always return 0

        except TemplateException as err:
            return self._process_error(err)

        except Exception as err:
            LOG.exception("Exception raised: %s", err)
            raise

    def handle_token(self, token):
        """Determine the resolution path based on the input id.

        This method is kept inside the BertE class for backward compatibility
        with the legacy Bert-E API (calling sys.argv/main()).

        Args:
          - token (str):
            - pull request id: handle the pull request update
            - sha1: analyse state of the queues,
                    only if the sha1 belongs to a queue

        Returns:
            - a Bert-E return code

        """
        if len(token) in SHA1_LENGTH:
            return self._handle_sha1(token)
        try:
            int(token)
        except ValueError:
            pass
        else:
            # it is probably a pull request id
            return self._handle_pull_request(token)
        return self._process_error(UnsupportedTokenType(token))

    def _process_error(self, error):
        if self.settings.backtrace:
            raise error from error
        LOG.info("Exception raised: %d", error.code)
        if not self.settings.quiet:
            print('%d - %s' % (0, error.__class__.__name__))
        return error.code

    def _handle_pull_request(self, pr_id):
        """Entry point to handle a pull request id."""
        job = PullRequestJob(
            bert_e=self,
            pull_request=self.project_repo.get_pull_request(int(pr_id))
        )
        return self.process(job)

    def _handle_sha1(self, sha1):
        """Entry point to handle a sha1 hash."""
        return self.process(CommitJob(bert_e=self, commit=sha1))

    def add_merged_pr(self, pr_id):
        """Add pr_id to the list of merged pull requests.

        This list is an inspectable dequeue containing the last 10 merged pull
        requests' IDs.

        """
        merged_prs = self.status.setdefault('merged PRs', deque(maxlen=10))
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
        for pr_id in queue_collection.queued_prs:
            status[pr_id] = []
        for version, queue in reversed(queues.items()):
            for branch in queue[qib]:
                status[branch.pr_id].append((version,
                                             branch.get_latest_commit()))
        self.status['merge queue'] = status


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
             "to analyse" % SHA1_LENGTH)
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
