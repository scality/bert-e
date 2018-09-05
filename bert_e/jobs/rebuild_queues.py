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
import logging

from bert_e import exceptions
from bert_e.job import APIJob, PullRequestJob, handler
from bert_e.workflow.git_utils import clone_git_repo, push
from bert_e.workflow.gitwaterflow.branches import (branch_factory,
                                                   build_queue_collection)


LOG = logging.getLogger(__name__)


class RebuildQueuesJob(APIJob):
    """Job that will rebuild the queues entirely."""
    @property
    def url(self) -> str:
        return ''

    def __str__(self):
        return "Rebuild queues"


@handler(RebuildQueuesJob)
def rebuild_queues(job: RebuildQueuesJob):
    """Rebuild the queues entirely."""
    if not job.settings.use_queue:
        raise exceptions.NotMyJob()
    repo = clone_git_repo(job)
    queue_collection = build_queue_collection(job)
    queued_prs = queue_collection.queued_prs
    LOG.debug('Currently queued PRs: %s', queued_prs)

    # Delete all q/* branches.
    queue_branches = [
        branch_factory(repo, b) for b in repo.remote_branches
        if b.startswith('q/')
    ]

    if not queue_branches:
        raise exceptions.JobSuccess()

    branch_factory(
        repo,
        'development/{}'.format(queue_branches[0].version)
    ).checkout()

    for branch in queue_branches:
        branch.remove(do_push=False)

    push(repo, prune=True)
    LOG.debug('Queues deleted, waking PRs up')

    # Trigger Bert-E on all previously queued PRs to rebuild the queue.
    for pr_id in queued_prs:
        job.bert_e.put_job(
            PullRequestJob(
                bert_e=job.bert_e,
                pull_request=job.project_repo.get_pull_request(pr_id)
            )
        )

    raise exceptions.JobSuccess()
