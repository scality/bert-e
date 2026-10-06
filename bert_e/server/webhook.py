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

"""This module defines the server webhook endpoints."""

import json
import logging

from flask import Blueprint, Response, current_app, request

from ..git_host import github
from ..git_host.bitbucket import BuildStatus, PullRequest
from ..git_host.cache import BUILD_STATUS_CACHE
from ..job import CommitJob, PullRequestJob
from .auth import requires_basic_auth

LOG = logging.getLogger(__name__)
blueprint = Blueprint('Bert-E server webhook endpoints', __name__)


def is_robot(bert_e, user_id):
    """Tell whether a git host user identifier designates Bert-E's robot.

    Args:
        - bert_e: the BertE instance whose settings define the robot.
        - user_id: a username, login or account_id sent by the git host.

    """
    if not user_id:
        return False
    robot = bert_e.settings.robot
    robot_ids = (robot.username, robot.account_id)
    return user_id.lower() in (str(rid).lower() for rid in robot_ids if rid)


def handle_bitbucket_repo_event(bert_e, event, json_data):
    """Handle a Bitbucket webhook sent on a repository event."""
    if event in ['commit_status_created', 'commit_status_updated']:
        build_status = json_data['commit_status']['state']
        key = json_data['commit_status']['key']
        build_url = json_data['commit_status']['url']
        commit_url = json_data['commit_status']['links']['commit']['href']
        commit_sha1 = commit_url.split('/')[-1]

        LOG.debug("New build status on commit %s", commit_sha1)

        # If we don't have a successful build for this sha1, update the cache
        cached = BUILD_STATUS_CACHE[key].get(commit_sha1, None)
        if not cached or cached.state != 'SUCCESSFUL':
            status = BuildStatus(bert_e.client, **json_data['commit_status'])
            BUILD_STATUS_CACHE[key].set(commit_sha1, status)

        # Ignore notifications that the build started
        if build_status == 'INPROGRESS':
            LOG.debug("The build just started on %s, ignoring event",
                      commit_sha1)
            return

        LOG.info('The build status of commit <%s> has been updated to %s. '
                 'More information at %s',
                 commit_sha1, build_status, build_url)
        return CommitJob(bert_e=bert_e, commit=commit_sha1)


def handle_bitbucket_pr_event(bert_e, event, json_data):
    """Handle a Bitbucket webhook sent on a pull request event."""
    pr_id = json_data['pullrequest']['id']
    if event.startswith('comment_'):
        actor = json_data.get('actor') or {}
        if any(is_robot(bert_e, actor.get(key))
               for key in ('account_id', 'username')):
            LOG.debug('Ignoring %s event on pull request <%s> sent by '
                      'the robot', event, pr_id)
            return
    pr = PullRequest(bert_e.client, **json_data['pullrequest'])
    LOG.info('The pull request <%s> has been updated', pr_id)
    return PullRequestJob(bert_e=bert_e, pull_request=pr)


def handle_github_pr_event(bert_e, json_data):
    """Handle a GitHub webhook sent on a pull request update event."""
    event = github.PullRequestEvent(client=bert_e.client, **json_data)
    pr = event.pull_request
    if event.action != "closed":
        return PullRequestJob(bert_e=bert_e, pull_request=pr)
    else:
        LOG.debug('PR #%s closed, ignoring event', pr.id)


def handle_github_issue_comment(bert_e, json_data):
    """Handle a GitHub webhook sent on an issue comment event."""
    sender = json_data.get('sender') or {}
    if is_robot(bert_e, sender.get('login')):
        LOG.debug("Ignoring issue comment event sent by the robot")
        return
    event = github.IssueCommentEvent(client=bert_e.client, **json_data)
    pr = event.pull_request
    if pr:
        return PullRequestJob(bert_e=bert_e, pull_request=pr)


def handle_github_pr_review_event(bert_e, json_data):
    """Handle a GitHub webhook sent on a pull request review event."""
    event = github.PullRequestReviewEvent(client=bert_e.client, **json_data)
    pr = event.pull_request
    LOG.debug("A review was submitted or dismissed on pull request #%d", pr.id)
    return PullRequestJob(bert_e=bert_e, pull_request=pr)


def handle_github_status_event(bert_e, json_data):
    """Handle a GitHub webhook sent on a commit sha1 build status event."""
    event = github.StatusEvent(client=bert_e.client, **json_data)
    status = event.status
    LOG.debug("New build status on commit %s", event.commit)
    cached = BUILD_STATUS_CACHE[status.key].get(event.commit)
    if not cached or cached.state != 'SUCCESSFUL':
        BUILD_STATUS_CACHE[status.key].set(event.commit, status)

    if status.state == 'INPROGRESS':
        LOG.debug("The build just started on %s, ignoring event", event.commit)
        return

    return CommitJob(bert_e=bert_e, commit=event.commit)


def handle_github_check_suite_event(bert_e, json_data):
    event = github.CheckSuiteEvent(client=bert_e.client, **json_data)
    status = event.status
    LOG.debug("New check suite status received on commit {event.commit}")
    cached = BUILD_STATUS_CACHE[status.key].get(event.commit)

    if not cached or cached.state != 'SUCCESSFUL':
        BUILD_STATUS_CACHE[status.key].set(event.commit, status)

    if status.state == "INPROGRESS":
        LOG.debug("The build just started on %s, ignoring event", event.commit)
        return

    return CommitJob(bert_e=bert_e, commit=event.commit)


@blueprint.route('/bitbucket', methods=['POST'])
@requires_basic_auth
def parse_bitbucket_webhook():
    """Entrypoint for handling a Bitbucket webhook."""
    # The event key of the event that triggers the webhook
    # for example, repo:push.
    entity, event = request.headers.get('X-Event-Key').split(':')
    json_data = json.loads(request.data.decode())
    LOG.debug('Received webhook from bitbucket:\n%s', json.dumps(json_data,
                                                                 indent=4))
    repo_owner = json_data['repository']['owner']['username']
    repo_slug = json_data['repository']['name']

    if repo_owner != current_app.bert_e.project_repo.owner:
        LOG.error('received repo_owner (%s) incompatible with settings',
                  repo_owner)
        return Response('Internal Server Error', 500)

    if repo_slug != current_app.bert_e.project_repo.slug:
        LOG.error('received repo_slug (%s) incompatible with settings',
                  repo_slug)
        return Response('Internal Server Error', 500)

    job = None
    if entity == 'repo':
        job = handle_bitbucket_repo_event(current_app.bert_e, event, json_data)
    if entity == 'pullrequest':
        job = handle_bitbucket_pr_event(current_app.bert_e, event, json_data)

    if not job:
        LOG.debug('Ignoring unhandled event %s:%s', entity, event)
        return Response('OK', 200)

    current_app.bert_e.put_job(job)
    return Response('OK', 200)


@blueprint.route('/github', methods=['POST'])
@requires_basic_auth
def parse_github_webhook():
    """Entrypoint for handling a GitHub webhook."""
    if current_app.bert_e.settings.repository_host != 'github':
        LOG.error('Received github webhook but Bert-E is configured '
                  'for %s', current_app.bert_e.settings.repository_host)
        return Response('Internal Server Error', 500)

    json_data = json.loads(request.data.decode())
    LOG.debug('Received webhook from github:\n%s', json.dumps(json_data,
                                                              indent=4))
    full_name = json_data.get('repository', {}).get('full_name')
    if full_name != current_app.bert_e.project_repo.full_name:
        LOG.debug('Received webhook for %s whereas I\'m handling %s. '
                  'Ignoring', full_name,
                  current_app.bert_e.project_repo.full_name)
        return Response('Internal Server Error', 500)

    event = request.headers.get('X-Github-Event')
    job = None
    LOG.debug("Received '%s' event", event)
    if event == 'pull_request':
        job = handle_github_pr_event(current_app.bert_e, json_data)
    elif event == 'issue_comment':
        job = handle_github_issue_comment(current_app.bert_e, json_data)
    elif event == 'pull_request_review':
        job = handle_github_pr_review_event(current_app.bert_e, json_data)
    elif event == 'status':
        job = handle_github_status_event(current_app.bert_e, json_data)
    elif event == 'check_suite':
        job = handle_github_check_suite_event(current_app.bert_e, json_data)

    if job is None:
        LOG.debug('Ignoring event.')
        return Response('OK', 200)

    current_app.bert_e.put_job(job)
    return Response('Accepted', 202)
