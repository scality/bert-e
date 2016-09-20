#!/usr/bin/env python
"""A python daemon that listens for webhooks coming from bitbucket and
launches, Wall-E accordingly.
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

import wall_e
if sys.version_info.major < 3:
    import Queue as queue
else:
    import queue


APP = Flask(__name__)
FIFO = queue.Queue()
DONE = deque(maxlen=1000)

try:
    SENTRY = Sentry(APP, logging=True, level=logging.INFO,
                    dsn=os.environ['SENTRY_DSN'])
except KeyError:
    SENTRY = None

Job = namedtuple('Job', ('repo_owner', 'repo_slug', 'revision', 'start_time'))


def wall_e_launcher():
    """Basic worker loop that waits for wall_e jobs and launches them."""
    pwd = os.environ['WALL_E_PWD']
    while True:
        job = FIFO.get()
        sys.argv[:] = []
        sys.argv.extend([
            'wall_e',
            '-v',
            '--owner', job.repo_owner,
            '--slug', job.repo_slug,
            str(job.revision),
            pwd
        ])
        try:
            wall_e.main()
        except Exception as err:
            if SENTRY:
                SENTRY.captureException()
            else:
                logging.error("Wall-e job %s finished with an error: %s",
                              job, err)
        finally:
            FIFO.task_done()

            logging.debug("It took Esteban %s to handle job %s:%s",
                          datetime.now() - job.start_time,
                          job.repo_slug, job.revision)
            DONE.appendleft(job)


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
    tasks = FIFO.queue
    output.append('{0} queued jobs:'.format(len(tasks)))
    output.extend('* [{3}] {0}/{1} - {2}'.format(*job) for job in tasks)
    output.append('\nCompleted jobs:')
    output.extend('* [{3}] {0}/{1} - {2}'.format(*job) for job in DONE)
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
    revision = None
    if entity == 'repo':
        revision = handle_repo_event(event, json_data)
    if entity == 'pullrequest':
        revision = handle_pullrequest_event(event, json_data)

    if not revision:
        logging.debug('Nothing to do')
        return Response('OK', 200)

    job = Job(repo_owner, repo_slug, revision, datetime.now())

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
        # Ignore notifications that the build started
        if build_status == 'INPROGRESS':
            return
        commit_url = json_data['commit_status']['links']['commit']['href']
        commit_sha1 = commit_url.split('/')[-1]
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
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help='verbose mode')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    worker = Thread(target=wall_e_launcher)
    worker.daemon = True
    worker.start()
    APP.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    main()
