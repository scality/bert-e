#!/usr/bin/env python
"""A python daemon that listens for webhooks coming from bitbucket and
launches, Bert-E accordingly.
"""
import argparse
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

            logging.debug("It took Esteban %s to handle job %s:%s",
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
    output = []

    merged_prs = bert_e.STATUS.get('merged PRs', [])
    merge_queue = bert_e.STATUS.get('merge queue', None)
    cur_job = bert_e.STATUS.get('current job', None)

    tasks = FIFO.queue
    if cur_job is not None:
        output.append('Current job: [{3}] {0}/{1} - {2}\n'.format(*cur_job))

    if merged_prs:
        output.append('Recently merged Pull Requests:')
        output.extend('* #{}'.format(pr_id) for pr_id in merged_prs)
        output.append('')

    if merge_queue:
        output.append('Merge queue status:')
        versions = set()
        for queued_commits in merge_queue.values():
            for version, _ in queued_commits:
                versions.add(version)

        versions = sorted(versions, reverse=True)
        header = (' ' * 10) + ''.join('{:^15}'.format(v) for v in versions)

        output.append(header)
        for pr_id, queued_commits in merge_queue.items():
            if int(pr_id) in merged_prs:
                continue
            build_status = {}
            for version, sha1 in queued_commits:
                build = BUILD_STATUS_CACHE['pre-merge'].get(sha1, 'INPROGRESS')
                build_status[version] = build

            output.append(
                '{:^10}{}'.format(
                    '#{}'.format(pr_id),
                    ''.join(
                        '{:^15}'.format(build_status.get(v, ''))
                        for v in versions
                    )
                )
            )
        if output[-1] == header:
            output.pop()
            output.pop()
        else:
            output.append('')

    output.append('{0} pending jobs:'.format(len(tasks)))
    output.extend('* [{start_time}] {repo_owner}/{repo_slug} - '
                  '{revision}'.format(**job._asdict()) for job in tasks)
    output.append('\nCompleted jobs:')
    output.extend('* [{start_time}] {repo_owner}/{repo_slug} - '
                  '{revision} -> {status}'.format(
                      status=status,
                      **job._asdict()
                  ) for job, status in DONE)

    return Response('\n'.join(output), mimetype='text/plain')


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
    settings_dir = APP.config.get('SETTINGS_DIR')
    repo_settings = settings_dir + '/' + repo_owner + '/' + repo_slug
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
        commit_url = json_data['commit_status']['links']['commit']['href']
        commit_sha1 = commit_url.split('/')[-1]

        # If we don't have a successful build for this sha1, update the cache
        if BUILD_STATUS_CACHE[key].get(commit_sha1, None) != 'SUCCESSFUL':
            BUILD_STATUS_CACHE[key].set(commit_sha1, build_status)

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
    parser.add_argument('--settings-dir', '-d', action='store',
                        default='/etc/bert-e/projects',
                        help='directory where settings files are stored '
                             '(defaults to /etc/bert-e/projects)')
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='verbose mode')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    worker = Thread(target=bert_e_launcher)
    worker.daemon = True
    worker.start()
    APP.config['SETTINGS_DIR'] = args.settings_dir
    APP.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    main()
