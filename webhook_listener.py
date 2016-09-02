#!/usr/bin/env python
"""A python daemon that listens for webhooks coming from bitbucket and
launches, Wall-E accordingly.
"""
import os
from flask import Flask, request
import json
import logging
import sys

from raven.contrib.flask import Sentry

import wall_e

from webhook_listener_auth import requires_auth

app = Flask(__name__)


@app.route('/bitbucket', methods=['POST'])
@requires_auth
def parse_bitbucket_webhook():
    # The event key of the event that triggers the webhook
    # for example, repo:push.
    entity, event = request.headers.get('X-Event-Key').split(':')
    json_data = json.loads(request.data)
    repo_owner = json_data['repository']['owner']['username']
    repo_slug = json_data['repository']['name']
    branch_or_commit_or_pr = None
    if entity == 'repo':
        branch_or_commit_or_pr = handle_repo_event(event, json_data)
    elif entity == 'pullrequest':
        branch_or_commit_or_pr = handle_pullrequest_event(event, json_data)

    if not branch_or_commit_or_pr:
        return

    sys.argv.extend([
        '-v',
        '--owner', repo_owner,
        '--slug', repo_slug,
        str(branch_or_commit_or_pr),
        os.environ['WALL_E_PWD']
    ])

    return wall_e.main()


def handle_repo_event(event, json_data):
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
    pr_id = json_data['pullrequest']['id']
    return pr_id


if __name__ == '__main__':
    assert os.environ['WEBHOOK_LOGIN']
    assert os.environ['WEBHOOK_PWD']
    try:
        sentry = Sentry(app, logging=True, level=logging.INFO,
                        dsn=os.environ['SENTRY_DSN'])
    except KeyError:
        pass
    app.run(host='0.0.0.0', port=5000, debug=True)
