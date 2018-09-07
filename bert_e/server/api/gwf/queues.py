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

from bert_e.jobs.delete_queues import DeleteQueuesJob
from bert_e.jobs.force_merge_queues import ForceMergeQueuesJob
from bert_e.jobs.rebuild_queues import RebuildQueuesJob

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
        '''
    form_inner_html = '''
        <button type="submit">delete</button>
        '''


class ForceMergeQueues(APIEndpoint):
    rule = '/gwf/queues'
    method = 'PATCH'
    admin = True
    job = ForceMergeQueuesJob


class ForceMergeQueuesForm(APIForm):
    endpoint_cls = ForceMergeQueues
    title = 'Force merge queues'
    help_text = '''
        <p>Create a job that will merge all pull requests currently in
        the queues, irrespective of the status of builds.</p>
        '''
    form_inner_html = '''
        <button type="submit">merge</button>
        '''
