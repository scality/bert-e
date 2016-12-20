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
import argparse
import jinja2
import json
import logging
import os
import sys
from collections import namedtuple, deque
from datetime import datetime
from functools import wraps
from threading import Thread

from flask import Flask, request, Response
from raven.contrib.flask import Sentry

from bitbucket_api import BUILD_STATUS_CACHE

import bert_e
import bert_e_exceptions

if sys.version_info.major < 3:
    import Queue as queue
else:
    import queue


APP = Flask(__name__)
FIFO = queue.Queue()
DONE = deque(maxlen=1000)
CODE_NAMES = {}

TXT_TEMPLATE = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            "txt_template")
HTML_TEMPLATE = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                             "html_template")

try:
    SENTRY = Sentry(APP, logging=True, level=logging.INFO,
                    dsn=os.environ['SENTRY_DSN'])
except KeyError:
    SENTRY = None

Job = namedtuple('Job', ('repo_owner', 'repo_slug',
                         'revision', 'start_time', 'repo_settings'))

# Populate code names.
for name in dir(bert_e_exceptions):
    obj = getattr(bert_e_exceptions, name)
    if not isinstance(obj, type):
        continue
    if not issubclass(obj, bert_e_exceptions.BertE_Exception):
        continue
    CODE_NAMES[obj.code] = name


def revision_link(revision):
    # Hack to make the difference between git commit and pull request id
    revision_length = len(revision)
    if revision_length == 40 or revision_length == 12:
        url = APP.config['COMMIT_BASE_URL']
        link = '<a href="%s">%s</a>' % (
                url.format(commit_id=revision), revision)
    else:
        url = APP.config['PULL_REQUEST_BASE_URL']
        link = '<a href="%s">%s</a>' % (
                url.format(pr_id=revision.replace('#', '')), revision)
    return link


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
            retcode = bert_e.main()
            status = CODE_NAMES.get(retcode, 'Unknown status: %s' % retcode)
        except Exception as err:
            if SENTRY:
                SENTRY.captureException()
            else:
                logging.error("Bert-E job %s finished with an error: %s",
                              job, err)
            retcode = getattr(err, 'code', None)
            status = CODE_NAMES.get(retcode, type(err).__name__)
        finally:
            FIFO.task_done()

            logging.debug("It took the server %s to handle job %s:%s",
                          datetime.now() - job.start_time,
                          job.repo_slug, job.revision)
            DONE.appendleft((job, status))
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

    merged_prs = bert_e.STATUS.get('merged PRs', [])
    merge_queue = bert_e.STATUS.get('merge queue', None)
    cur_job = bert_e.STATUS.get('current job', None)

    tasks = FIFO.queue

    output_vars = {}

    if cur_job is not None:
        if output_mode == 'html':
            current_job = Job(cur_job.repo_owner, cur_job.repo_slug,
                              revision_link(cur_job.revision),
                              cur_job.start_time, cur_job.repo_settings)
        else:
            current_job = cur_job
        output_vars['cur_job'] = current_job

    if merged_prs:
        output_vars['merged_prs'] = []
        for i in merged_prs:
            if output_mode == 'html':
                output_vars['merged_prs'].append(revision_link('#%d' % i))
            else:
                output_vars['merged_prs'].append('#%d' % i)

    if merge_queue:
        versions = set()
        for queued_commits in merge_queue.values():
            for version, _ in queued_commits:
                versions.add(version)

        versions = sorted(versions, reverse=True)

        headers = [(' ' * 10)]
        headers.extend('{:^15}'.format(v) for v in versions)
        output_vars['merge_queue'] = [headers]
        for pr_id, queued_commits in merge_queue.items():
            if int(pr_id) in merged_prs:
                continue
            build_status = {}
            for version, sha1 in queued_commits:
                build = BUILD_STATUS_CACHE['pre-merge'].get(sha1, 'INPROGRESS')
                if output_mode == 'html':
                    url = BUILD_STATUS_CACHE['pre-merge'].get('%s-build' %
                                                              sha1, '')
                    build_status[version] = '<a href="%s">%s</a>' % (url,
                                                                     build)
                else:
                    build_status[version] = '{:^15}'.format(build)

            if output_mode == 'html':
                merge_queue_pr = [revision_link('#%d' % int(pr_id))]
            else:
                merge_queue_pr = ['{:^10}'.format('#%d' % int(pr_id))]

            merge_queue_pr.extend(build_status.get(v, ' ' * 15)
                                  for v in versions)

            output_vars['merge_queue'].append(merge_queue_pr)

    output_vars['pending_jobs'] = []
    for i in tasks:
        if output_mode == 'html':
            i = Job(i.repo_owner, i.repo_slug, revision_link(i.revision),
                    i.start_time, i.repo_settings)
        output_vars['pending_jobs'].append(i._asdict())

    output_vars['completed_jobs'] = []
    for i, j in DONE:
        if output_mode == 'html':
            i = Job(i.repo_owner, i.repo_slug, revision_link(i.revision),
                    i.start_time, i.repo_settings)
        output_vars['completed_jobs'].append([j, i._asdict()])

    if output_mode == 'txt':
        output_mimetype = 'text/plain'
        path_template, file_template = os.path.split(TXT_TEMPLATE)
    else:
        output_mimetype = 'text/html'
        path_template, file_template = os.path.split(HTML_TEMPLATE)

    output_render = jinja2.Environment(
        loader=jinja2.FileSystemLoader(path_template or './')
    ).get_template(file_template).render(output_vars)

    return Response(output_render, mimetype=output_mimetype)


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


def main():
    """Program entry point."""
    parser = argparse.ArgumentParser(
        add_help=True,
        description='Handles webhook calls.'
    )

    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='server host (defaults to 0.0.0.0)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='server port (defaults to 5000)')
    parser.add_argument('--settings-file', '-f', type=str, required=True,
                        help='settings-file location')
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='verbose mode')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    worker = Thread(target=bert_e_launcher)
    worker.daemon = True
    worker.start()

    settings = bert_e.setup_settings(args.settings_file)

    APP.config['SETTINGS_FILE'] = args.settings_file
    APP.config['PULL_REQUEST_BASE_URL'] = settings['pull_request_base_url']
    APP.config['COMMIT_BASE_URL'] = settings['commit_base_url']
    APP.config['REPOSITORY_OWNER'] = settings['repository_owner']
    APP.config['REPOSITORY_SLUG'] = settings['repository_slug']
    APP.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    main()
