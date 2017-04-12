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

"""A python daemon that listens for webhooks coming from bitbucket and
launches, Bert-E accordingly.
"""
import json
import logging
import os
import pkg_resources
from functools import wraps

from flask import Flask, Response, render_template, request

from .git_host import github
from .git_host.bitbucket import BUILD_STATUS_CACHE, PullRequest
from .job import CommitJob, PullRequestJob

BERTE = None
APP = Flask(__name__)
LOG = logging.getLogger(__name__)


@APP.template_filter('pr_url')
def pr_url_filter(id_or_revision):
    config = BERTE.settings
    if len(str(id_or_revision)) in [12, 40]:
        return config.commit_base_url.format(commit_id=id_or_revision)
    else:
        return config.pull_request_base_url.format(pr_id=id_or_revision)


@APP.template_filter('build_url')
def build_url_filter(sha1):
    return BUILD_STATUS_CACHE['pre-merge'].get('%s-build' % sha1, '')


def bert_e_launcher():
    """Basic worker loop that waits for Bert-E jobs and launches them."""
    while True:
        BERTE.process_task()


def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == os.environ['WEBHOOK_LOGIN'] and \
        password == os.environ['WEBHOOK_PWD']


def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})


def requires_auth(func):
    """Decorator to require auth on selected operations."""
    @wraps(func)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return func(*args, **kwargs)
    return decorated


@APP.route('/', methods=['GET'])
def display_queue():
    output_mode = request.args.get('output')
    if output_mode is None:
        output_mode = 'html'

    current_job = BERTE.status.get('current job', None)
    merged_prs = BERTE.status.get('merged PRs', [])
    queue_data = BERTE.status.get('merge queue', None)
    pending_jobs = BERTE.task_queue.queue

    queue_lines = []
    versions = set()
    if queue_data:
        for queued_commits in queue_data.values():
            for version, _ in queued_commits:
                versions.add(version)

        versions = sorted(versions, reverse=True)

        for pr_id, queued_commits in queue_data.items():
            if int(pr_id) in [i['id'] for i in merged_prs]:
                continue
            line = {'pr_id': pr_id}
            for version, sha1 in queued_commits:
                line[version] = {
                    'sha1': sha1,
                    'status':
                        BUILD_STATUS_CACHE['pre-merge'].get(sha1, 'NOTSTARTED')
                }
            queue_lines.append(line)

    if output_mode == 'txt':
        output_mimetype = 'text/plain'
        file_template = 'status.txt'
    else:
        output_mimetype = 'text/html'
        file_template = 'status.html'

    try:
        bert_e_version = pkg_resources.require("bert-e")[0].version
    except Exception:
        bert_e_version = 'unset_version'

    return render_template(
        file_template,
        bert_e_version=bert_e_version,
        owner=BERTE.project_repo.owner,
        slug=BERTE.project_repo.slug,
        current_job=current_job,
        merged_prs=merged_prs,
        queue_lines=queue_lines,
        versions=versions,
        pending_jobs=pending_jobs,
        completed_jobs=BERTE.tasks_done
    ), 200, {'Content-Type': output_mimetype}


@APP.route('/bitbucket', methods=['POST'])
@requires_auth
def parse_bitbucket_webhook():
    """React to a webhook event coming from bitbucket."""
    # The event key of the event that triggers the webhook
    # for example, repo:push.
    entity, event = request.headers.get('X-Event-Key').split(':')
    json_data = json.loads(request.data.decode())
    repo_owner = json_data['repository']['owner']['username']
    repo_slug = json_data['repository']['name']

    if repo_owner != BERTE.project_repo.owner:
        LOG.error('received repo_owner (%s) incompatible with settings',
                  repo_owner)
        return Response('Internal Server Error', 500)

    if repo_slug != BERTE.project_repo.slug:
        LOG.error('received repo_slug (%s) incompatible with settings',
                  repo_slug)
        return Response('Internal Server Error', 500)

    job = None
    if entity == 'repo':
        job = handle_repo_event(event, json_data)
    if entity == 'pullrequest':
        job = handle_pullrequest_event(event, json_data)

    if not job:
        LOG.debug('Ignoring unhandled event %s:%s', entity, event)
        return Response('OK', 200)

    BERTE.put_job(job)
    return Response('OK', 200)


def handle_repo_event(event, json_data):
    """Handle repository event.

    Parse the event's JSON for interesting events
    ('commit_status_created', 'commit_status_updated') and return
    the corresponding git rev-spec to analyse.

    """
    if event in ['commit_status_created', 'commit_status_updated']:
        build_status = json_data['commit_status']['state']
        key = json_data['commit_status']['key']
        build_url = json_data['commit_status']['url']
        commit_url = json_data['commit_status']['links']['commit']['href']
        commit_sha1 = commit_url.split('/')[-1]

        # If we don't have a successful build for this sha1, update the cache
        if BUILD_STATUS_CACHE[key].get(commit_sha1, None) != 'SUCCESSFUL':
            BUILD_STATUS_CACHE[key].set(commit_sha1, build_status)
            BUILD_STATUS_CACHE[key].set('%s-build' % commit_sha1, build_url)

        # Ignore notifications that the build started
        if build_status == 'INPROGRESS':
            return

        LOG.info('The build status of commit <%s> has been updated to %s. '
                 'More information at %s',
                 commit_sha1, build_status, build_url)
        return CommitJob(bert_e=BERTE, commit=commit_sha1, url=build_url)


def handle_pullrequest_event(event, json_data):
    """Handle an event on a pull-request.

    Parse the PR event and return the pull request's ID

    """
    pr_id = json_data['pullrequest']['id']
    pr_url = json_data['pullrequest']['links']['html']['href']
    pr = PullRequest(BERTE.client, **json_data['pullrequest'])
    LOG.info('The pull request <%s> has been updated', pr_id)
    return PullRequestJob(bert_e=BERTE, pull_request=pr, url=pr_url)


@APP.route('/github', methods=['POST'])
@requires_auth
def parse_github_webhook():
    if BERTE.settings.repository_host != 'github':
        LOG.error('Received github webhook but Bert-E is configured for %s',
                  BERTE.settings.repository_host)
        return Response('Internal Server Error', 500)

    json_data = json.loads(request.data.decode())
    full_name = json_data.get('repository', {}).get('full_name')
    if full_name != BERTE.project_repo.full_name:
        LOG.debug("Received webhook for %s whereas I'm handling %s. Ignoring",
                  full_name, BERTE.project_repo.full_name)
        return Response('Internal Server Error', 500)

    event = request.headers.get('X-Github-Event')
    job = None
    LOG.debug("Received '%s' event", event)
    if event == 'pull_request':
        job = handle_github_pr_event(BERTE.client, json_data)
    elif event == 'issue_comment':
        job = handle_github_issue_comment(BERTE.client, json_data)
    elif event == 'pull_request_review':
        job = handle_github_pr_review_event(BERTE.client, json_data)
    elif event == 'status':
        job = handle_github_status_event(BERTE.client, json_data)

    if job is None:
        LOG.debug('Ignoring event.')
        return Response('OK', 200)

    BERTE.put_job(job)
    return Response('Accepted', 202)


def handle_github_pr_event(client, json_data):
    event = github.PullRequestEvent(client=client, **json_data)
    pr = event.pull_request
    if event.action != "closed":
        return PullRequestJob(bert_e=BERTE, pull_request=pr, url=pr.url)
    else:
        LOG.debug('PR #%s closed, ignoring event', pr.id)


def handle_github_issue_comment(client, json_data):
    event = github.IssueCommentEvent(client=client, **json_data)
    pr = event.pull_request
    if pr:
        return PullRequestJob(bert_e=BERTE, pull_request=pr, url=pr.url)


def handle_github_pr_review_event(client, json_data):
    event = github.PullRequestReviewEvent(client=client, **json_data)
    pr = event.pull_request
    LOG.debug("A review was submitted or dismissed on pull request #%d", pr.id)
    return PullRequestJob(bert_e=BERTE, pull_request=pr, url=pr.url)


def handle_github_status_event(client, json_data):
    event = github.StatusEvent(client=client, **json_data)
    status = event.status
    LOG.debug("New build status on commit %s", event.commit)
    cached = github.BUILD_STATUS_CACHE[status.key].get(event.commit)
    if not cached or cached.state != 'SUCCESSFUL':
        github.BUILD_STATUS_CACHE[status.key].set(event.commit, status)

    if status.state == 'INPROGRESS':
        LOG.debug("The build just started on %s, ignoring event", event.commit)
        return

    commit_url = json_data['commit']['html_url']
    return CommitJob(bert_e=BERTE, commit=event.commit, url=commit_url)
