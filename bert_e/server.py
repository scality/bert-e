#!/usr/bin/env python

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
import sys
from collections import deque, namedtuple
from datetime import datetime
from functools import wraps

from flask import Flask, request, Response, render_template
from raven.contrib.flask import Sentry

from . import bert_e, exceptions
from .api.bitbucket import BUILD_STATUS_CACHE
from .exceptions import BertE_Exception, InternalException

if sys.version_info.major < 3:
    import Queue as queue
else:
    import queue


APP = Flask(__name__)
FIFO = queue.Queue()
DONE = deque(maxlen=1000)
CODE_NAMES = {}

try:
    SENTRY = Sentry(APP, logging=True, level=logging.INFO,
                    dsn=os.environ['SENTRY_DSN'])
except KeyError:
    SENTRY = None

Job = namedtuple('Job', ('repo_owner', 'repo_slug',
                         'revision', 'start_time', 'repo_settings'))

# Populate code names.
for name in dir(exceptions):
    obj = getattr(exceptions, name)
    if not isinstance(obj, type):
        continue
    if not issubclass(obj, exceptions.BertE_Exception):
        continue
    CODE_NAMES[obj.code] = name


@APP.template_filter('pr_url')
def pr_url_filter(id_or_revision):
    if len(str(id_or_revision)) in [12, 40]:
        return APP.config['COMMIT_BASE_URL'].format(commit_id=id_or_revision)
    else:
        return APP.config['PULL_REQUEST_BASE_URL'].format(pr_id=id_or_revision)


@APP.template_filter('build_url')
def build_url_filter(sha1):
    return BUILD_STATUS_CACHE['pre-merge'].get('%s-build' % sha1, '')


def bert_e_launcher():
    """Basic worker loop that waits for Bert-E jobs and launches them."""
    bb_pwd = os.environ['BERT_E_BB_PWD']
    jira_pwd = os.environ['BERT_E_JIRA_PWD']
    while True:
        job = FIFO.get()
        sys.argv[:] = []
        bert_e.STATUS['current job'] = job
        sys.argv.extend([
            'bert_e',
            '-v',
            '--backtrace'
        ])
        sys.argv.extend([
            job.repo_settings,
            bb_pwd,
            jira_pwd,
            str(job.revision)
        ])
        try:
            bert_e.main()
        except Exception as err:
            # with '--backtrace', all instances will raise
            retcode = getattr(err, 'code', None)
            status = CODE_NAMES.get(retcode, type(err).__name__)
            details = None

            if (not isinstance(err, BertE_Exception) or
                    isinstance(err, InternalException)):
                logging.error("Bert-E job %s finished with an error: %s",
                              job, err)
                details = err.message
                if SENTRY:
                    SENTRY.captureException()
        finally:
            FIFO.task_done()

            logging.debug("It took the server %s to handle job %s:%s",
                          datetime.now() - job.start_time,
                          job.repo_slug, job.revision)
            DONE.appendleft({'job': job, 'status': status, 'details': details})
            bert_e.STATUS.pop('current job')


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

    current_job = bert_e.STATUS.get('current job', None)
    merged_prs = bert_e.STATUS.get('merged PRs', [])
    queue_data = bert_e.STATUS.get('merge queue', None)
    pending_jobs = FIFO.queue

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
                        BUILD_STATUS_CACHE['pre-merge'].get(sha1, 'INPROGRESS')
                }
            queue_lines.append(line)

    if output_mode == 'txt':
        output_mimetype = 'text/plain'
        file_template = 'status.txt'
    else:
        output_mimetype = 'text/html'
        file_template = 'status.html'

    return render_template(
        file_template,
        owner=APP.config['REPOSITORY_OWNER'],
        slug=APP.config['REPOSITORY_SLUG'],
        current_job=current_job,
        merged_prs=merged_prs,
        queue_lines=queue_lines,
        versions=versions,
        pending_jobs=pending_jobs,
        completed_jobs=DONE
    ), 200, {'Content-Type': output_mimetype}


@APP.route('/bitbucket', methods=['POST'])
@requires_auth
def parse_bitbucket_webhook():
    """React to a webhook event coming from bitbucket."""
    # The event key of the event that triggers the webhook
    # for example, repo:push.
    entity, event = request.headers.get('X-Event-Key').split(':')
    json_data = json.loads(request.data)
    repo_owner = json_data['repository']['owner']['username']
    repo_slug = json_data['repository']['name']

    if repo_owner != APP.config['REPOSITORY_OWNER']:
        logging.error('received repo_owner (%s) incompatible with settings' %
                      repo_owner)
        return Response('Internal Server Error', 500)

    if repo_slug != APP.config['REPOSITORY_SLUG']:
        logging.error('received repo_slug (%s) incompatible with settings' %
                      repo_slug)
        return Response('Internal Server Error', 500)

    repo_settings = APP.config.get('SETTINGS_FILE')
    revision = None
    if entity == 'repo':
        revision = handle_repo_event(event, json_data)
    if entity == 'pullrequest':
        revision = handle_pullrequest_event(event, json_data)

    if not revision:
        logging.debug('Nothing to do')
        return Response('OK', 200)

    job = Job(repo_owner, repo_slug, revision, datetime.now(), repo_settings)

    if any(filter(lambda j: j[:3] == job[:3], FIFO.queue)):
        logging.info('%s/%s:%s already in queue. Skipping.', *(job[:3]))
        return Response('OK', 200)

    logging.info('Queuing job %s', job)
    FIFO.put(job)

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
        logging.info('The build status of commit <%s> has been updated: %s',
                     commit_sha1, commit_url)
        return commit_sha1


def handle_pullrequest_event(event, json_data):
    """Handle an event on a pull-request.

    Parse the PR event and return the pull request's ID

    """
    pr_id = json_data['pullrequest']['id']
    logging.info('The pull request <%s> has been updated', pr_id)
    return str(pr_id)
