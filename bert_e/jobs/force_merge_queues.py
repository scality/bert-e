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

from bert_e import exceptions
from bert_e.job import APIJob, QueuesJob, handler
from bert_e.workflow.gitwaterflow.queueing import handle_merge_queues


class ForceMergeQueuesJob(APIJob):
    """Job that will delete the queues entirely."""
    @property
    def url(self) -> str:
        return ''

    def __str__(self):
        return "Force merge queues"


@handler(ForceMergeQueuesJob)
def force_merge_queues(job: ForceMergeQueuesJob):
    """Force merge the queues."""
    if not job.settings.use_queue:
        raise exceptions.NotMyJob()

    handle_merge_queues(QueuesJob(bert_e=job.bert_e, force_merge=True))
