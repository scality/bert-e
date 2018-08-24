# Copyright 2017 Scality
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

import re

from bert_e import exceptions
from bert_e.job import handler, PullRequestJob
from bert_e.lib.pull_request import send_comment

from .. import handle_pull_request


def _get_parent_pull_request(job):
    """Handle the parent of an integration pull request."""
    ids = re.findall('\d+', job.pull_request.description)
    if not ids:
        raise exceptions.ParentPullRequestNotFound(job.pull_request.id)
    parent_id, *_ = ids

    return parent_id


@handler(PullRequestJob)
def handle_webhook_pull_request(job: PullRequestJob):
    """Analyse and handle a pull request that has just been updated."""
    if job.pull_request.author == job.settings.robot_username:
        parent_id = _get_parent_pull_request(job)
        job = PullRequestJob(
            bert_e=job.bert_e,
            pull_request=job.project_repo.get_pull_request(int(parent_id))
        )

    try:
        handle_pull_request(job)
    except exceptions.TemplateException as err:
        send_comment(job.settings, job.pull_request, err)
        raise
