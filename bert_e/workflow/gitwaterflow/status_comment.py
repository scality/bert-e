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
"""Always up-to-date status comment of a pull request.

Bert-E posts a new comment at each step, which makes the current state of a
pull request hard to find. In addition, it maintains a single comment, edited
in place, which gives the latest state of the pull request, its integration
branches / pull requests and the status of their builds.

The comment is never part of the pull request description.
"""
import logging
import re

import requests

from bert_e import exceptions
from bert_e.git_host.base import Error as GitHostError
from bert_e.lib import git
from bert_e.lib.schema import SchemaError
from bert_e.lib.simplecmd import CommandError
from bert_e.lib.template_loader import render
from ..git_utils import clone_git_repo
from ..pr_utils import (STATUS_COMMENT_HEADER, find_status_comment,
                        upsert_status_comment)
from .commands import _build_status_report
from .integration import get_integration_branches

LOG = logging.getLogger(__name__)

# Errors that must not prevent Bert-E from going on when it cannot refresh the
# status comment: the git host or the git repository are unreachable, or the
# repository is in a state we do not understand (reported by the main flow).
EXPECTED_ERRORS = (
    requests.exceptions.RequestException, GitHostError, SchemaError,
    exceptions.FlakyGitHost, exceptions.InternalException,
    git.GitException, CommandError,
)

ICONS = {
    'success': ':white_check_mark:',
    'failure': ':x:',
    'in_progress': ':hourglass_flowing_sand:',
    'queued': ':hourglass:',
    None: ':information_source:',
}

# Silent exceptions which nevertheless describe a state of the pull request.
SILENT_STATES = {
    exceptions.BuildInProgress: 'Waiting for the builds to complete',
    exceptions.BuildNotStarted: 'Waiting for the builds to start',
    exceptions.PullRequestDeclined: 'Declined',
    exceptions.NothingToDo: 'Nothing to do',
}

# Silent states which are only published when a status comment already exists
# (never create a comment on closed or already merged pull requests).
UPDATE_ONLY = (exceptions.PullRequestDeclined, exceptions.NothingToDo)

# States for which the integration data and the checklist (approvals,
# builds...) are meaningless, or not worth the git host API calls (build
# states are very frequent and the API is rate limited).
FINAL_STATES = (exceptions.SuccessMessage, exceptions.PartialMerge,
                exceptions.PullRequestDeclined, exceptions.NothingToDo,
                exceptions.BuildInProgress, exceptions.BuildNotStarted)


class State:
    """The state of a pull request, as reported by Bert-E."""

    def __init__(self, label, status=None, code=None, final=False):
        self.label = label
        self.status = status
        self.code = code
        self.final = final

    @property
    def icon(self):
        return ICONS.get(self.status, ICONS[None])

    @classmethod
    def initial(cls):
        return cls('Being analyzed', 'in_progress')

    @classmethod
    def from_exception(cls, exc):
        """Return the state described by an exception, or None if it does
        not describe any (information, answer to a command...)."""
        if isinstance(exc, exceptions.TemplateException):
            if not exc.reports_state:
                return None
            label = exc.state_label or re.sub(
                r'(?<=[a-z])(?=[A-Z])', ' ', type(exc).__name__).capitalize()
            return cls(label, exc.state_status or exc.status, exc.code,
                       final=isinstance(exc, FINAL_STATES))
        label = SILENT_STATES.get(type(exc))
        if label is None:
            return None
        return cls(label, exc.status, final=isinstance(exc, FINAL_STATES))


def _integration_rows(job):
    """List the existing integration branches, their open pull requests and
    their build status.

    This is read from the repository and the git host each time, so that it
    follows resets, declined pull requests and recreated branches.
    """
    wbranches = list(get_integration_branches(job))
    names = [b.name for b in wbranches]
    prs = {}
    if names:
        prs = {pr.src_branch: pr for pr in
               job.project_repo.get_pull_requests(src_branch=names)
               if pr.status == 'OPEN'}
    key = job.settings.build_key
    rows = []
    for branch in wbranches:
        pr = prs.get(branch.name)
        build = None
        if key:
            build = job.project_repo.get_build_status(
                branch.get_latest_commit(), key)
        rows.append({'branch': branch.name,
                     'pr_id': pr.id if pr else None,
                     'build': build})
    return rows


def render_status(job, state, with_git=True):
    """Render the status comment.

    Args:
        with_git: whether to look at the git repository and the integration
                  pull requests. Not possible outside of a pull request job.

    """
    integration = None
    report = {}
    if (with_git and not state.final and
            job.git.src_branch and job.git.dst_branch):
        clone_git_repo(job)
        repo = job.project_repo
        original = repo.get_build_status
        cache = {}

        def cached_build_status(revision, key):
            if (revision, key) not in cache:
                cache[(revision, key)] = original(revision, key)
            return cache[(revision, key)]

        # share the build statuses between the table and the checklist
        repo.get_build_status = cached_build_status
        try:
            integration = _integration_rows(job)
            report = _build_status_report(job)
        finally:
            del repo.get_build_status
    msg = render('pr_status.md', icon=state.icon, label=state.label,
                 code=state.code, integration=integration, status=report,
                 active_options=job.active_options)
    if not msg.startswith(STATUS_COMMENT_HEADER):
        LOG.error("The status comment lacks its header")
    return msg


def publish_status(job, outcome, pull_request=None, with_git=True):
    """Update the pull request's status comment according to the outcome of
    a run (an exception, or a State).

    Failing to do so is never fatal.
    """
    if not job.settings.pr_status_comment:
        return
    state = outcome if isinstance(outcome, State) else \
        State.from_exception(outcome)
    if state is None:
        return
    try:
        if (isinstance(outcome, UPDATE_ONLY) and
                find_status_comment(pull_request or job.pull_request,
                                    job.settings.robot) is None):
            # do not add comments on closed pull requests which never had one
            return
        upsert_status_comment(
            job.settings, pull_request or job.pull_request,
            render_status(job, state, with_git))
    except EXPECTED_ERRORS:
        LOG.warning("Could not update the status comment of pull request %s",
                    (pull_request or job.pull_request).id, exc_info=True)
    except Exception:
        LOG.exception("Unexpected error while updating the status comment "
                      "of pull request %s",
                      (pull_request or job.pull_request).id)


def ensure_status_comment(job):
    """Make sure the pull request has a status comment, as early as possible
    so that it stays close to the description."""
    if (job.settings.pr_status_comment and
            find_status_comment(job.pull_request, job.settings.robot) is None):
        publish_status(job, State.initial(), with_git=False)
