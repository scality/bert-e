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

from bert_e.jobs.rebuild_queues import RebuildQueuesJob
from bert_e.jobs.delete_queues import DeleteQueuesJob

from ..base import APIEndpoint, APIForm


class RebuildQueues(APIEndpoint):
    rule = '/gwf/queues'
    method = 'POST'
    admin = False
    job = RebuildQueuesJob


class RebuildQueuesForm(APIForm):
    endpoint_cls = RebuildQueues
    title = 'Rebuild queues'
    help_text = '''
        <p>Create a job that will reset all queues and reconstruct them
        automatically.</p>

        <p>When to use this:</p>

        <ul>
        <li>When Bert-E reports that queues are out of order,</li>
        <li>When it is required to remove a pull request from the queue,
        before it is merged to the target development branches. In this case,
        comment the said pull request with a <strong>wait</strong> comment to
        Bert-E, then instruct the robot to rebuild the queues.</li>
        </ul>

        <p>This can also be activated on api endpoint
        <strong>/api/queues[POST]</strong>.</p>
        '''
    form_inner_html = '''
        <button type="submit">rebuild</button>
        '''


class DeleteQueues(APIEndpoint):
    rule = '/gwf/queues'
    method = 'DELETE'
    admin = True
    job = DeleteQueuesJob


class DeleteQueuesForm(APIForm):
    endpoint_cls = DeleteQueues
    title = 'Delete queues'
    help_text = '''
        <p>Create a job that will remove all queue data created by
        Bert-E.</p>

        <p>Can be used as a last resort when Bert-E reports a status of
        QueueOutOfOrder for example.</p>

        <p>All branches q/ will be safely removed from the repository. The
        queues will be recreated automatically on the next job. Any pull
        request that was queued at the time of the reset will <strong>NOT
        </strong> be queued anymore. It will be required to evaluate each
        pull request manually to add them to the queues again
        (see /api/pull-requests/&lt;id&gt;, or comment the pull requests
        accordingly).
        </p>

        <p>This can also be activated on api endpoint
        <strong>/api/queues[DELETE]</strong>.</p>
        '''
    form_inner_html = '''
        <button type="submit">delete</button>
        '''
