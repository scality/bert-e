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

"""This module defines the server status page."""

from flask import Blueprint, current_app, render_template, request

from ..git_host.cache import BUILD_STATUS_CACHE


blueprint = Blueprint('status page', __name__)


@blueprint.route('/', methods=['GET'])
def display():
    """Build and render the status page."""
    build_key = current_app.bert_e.settings.build_key
    output_mode = request.args.get('output')
    if output_mode is None:
        output_mode = 'html'

    current_job = current_app.bert_e.status.get('current job', None)
    merged_prs = current_app.bert_e.status.get('merged PRs', [])
    queue_data = current_app.bert_e.status.get('merge queue', None)
    pending_jobs = list(current_app.bert_e.task_queue.queue)
    pending_jobs.reverse()

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
                status = BUILD_STATUS_CACHE[build_key].get(sha1, None)
                state = status.state if status else 'NOTSTARTED'
                line[version] = {
                    'sha1': sha1,
                    'status': state,
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
        navigation=request.args.get('navoff', True),
        current_job=current_job,
        merged_prs=merged_prs,
        queue_lines=queue_lines,
        versions=versions,
        pending_jobs=pending_jobs,
        completed_jobs=current_app.bert_e.tasks_done
    ), 200, {'Content-Type': output_mimetype}
