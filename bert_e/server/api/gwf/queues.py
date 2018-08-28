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

from bert_e.api import RebuildQueuesJob

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
        <strong>/api/rebuild_queues</strong>.</p>
        '''
    form_inner_html = '''
        <button type="submit">rebuild</button>
        '''
