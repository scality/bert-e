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

"""This module defines the server api endpoints."""

import logging

from flask import Blueprint, Response, current_app, redirect, request, url_for

from ..api import EvalPullRequestJob, RebuildQueuesJob
from .auth import invalid, requires_auth


LOG = logging.getLogger(__name__)
blueprint = Blueprint('api', __name__)


@blueprint.route('/api/pull-requests/<int:pr_id>', methods=['POST'])
@requires_auth()
def pull_request(pr_id):
    LOG.info("Received 'eval' order for pr %d", pr_id)

    if pr_id < 1:
        return invalid()

    job = EvalPullRequestJob(pr_id, bert_e=current_app.bert_e)
    current_app.bert_e.put_job(job)

    if request.is_json:
        return Response(job.json(), 202,
                        {'Content-Type': 'text/json'})

    return redirect(url_for('status page.display'), code=302)


@blueprint.route('/api/gwf/queues', methods=['POST'])
@requires_auth()
def rebuild_queues():
    LOG.info("Received 'rebuild_queues' order")
    job = RebuildQueuesJob(bert_e=current_app.bert_e)
    current_app.bert_e.put_job(job)

    if request.is_json:
        return Response(job.json(), 202,
                        {'Content-Type': 'text/json'})

    return redirect(url_for('status page.display'), code=302)
