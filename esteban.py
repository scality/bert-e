#!/usr/bin/env python
"""A python daemon that listens for webhooks coming from bitbucket and
launches, Wall-E accordingly.
"""
import argparse
from collections import namedtuple
from datetime import datetime
from functools import wraps
import json
import logging
import os
import sys
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
        sys.argv.clear()
        sys.argv.extend([
            'wall_e',
            '-v',
            '--owner', job.repo_owner,
            '--slug', job.repo_slug,
            job.revision,
            pwd
        ])

        try:
            wall_e.main()
        except Exception as err:
            if SENTRY:
                SENTRY.captureException()
            else:
                logging.error(err)

        logging.debug("It took Esteban %s to handle job %s:%s",
                      datetime.now() - job.start_time, job.repo_slug, job.rev)


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
    return str(list(FIFO.queue))


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
    branch_or_commit_or_pr = None
    if entity == 'repo':
        revision = handle_repo_event(event, json_data)
    elif entity == 'pullrequest':
        revision = handle_pullrequest_event(event, json_data)

    if not revision:
        logging.debug('Nothing to do')
        return Response('OK', 200)

    logging.info('Queuing job %s:%s', repo_slug, revision)
    FIFO.put(Job(repo_owner, repo_slug, revision, datetime.now()))

    return Response('OK', 200)


def handle_repo_event(event, json_data):
    """Handle repository event.

    Parse the event's JSON for interesting events
    ('push', 'commit_status_created', 'commit_status_updated') and return
    the corresponding git rev-spec to analyse.

    """
    if event == 'push':
        if 'new' not in json_data['push']:
            # a branch has been deleted, ignoring...
            return
        push_type = json_data['push']['new']['type']
        if push_type != 'branch':
            return
        branch_name = json_data['push']['new']['name']
        return branch_name

    if event in ['commit_status_created', 'commit_status_updated']:
        commit_url = json_data['commit_status']['links']['commit']['href']
        commit_sha1 = commit_url.split('/')[-1]
        return commit_sha1


def handle_pullrequest_event(event, json_data):
    """Handle an event on a pull-request.

    Parse the PR event and return the pull request's ID

    """
    pr_id = json_data['pullrequest']['id']
    return pr_id


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

    #assert os.environ['WEBHOOK_LOGIN']
    #assert os.environ['WEBHOOK_PWD']

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    worker = Thread(target=wall_e_launcher)
    worker.daemon = True
    worker.start()
    APP.run(host=args.host, port=args.port, debug=args.verbose)


if __name__ == '__main__':
    main()
