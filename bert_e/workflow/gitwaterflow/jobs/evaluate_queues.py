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

from copy import deepcopy

from bert_e import exceptions
from bert_e.job import RepoJob, handler
from bert_e.lib.git import clone_git_repo, push

from ..queueing import (BranchCascade, build_queue_collection,
                        close_queued_pull_request, merge_queues)


class QueuesJob(RepoJob):
    """Job triggered when the queues were updated."""
    def __str__(self):
        return "Evaluate queues"


@handler(QueuesJob)
def handle_merge_queues(job):
    """Check merge queue and fast-forward development branches to the most
    recent stable state.

    """
    cascade = job.git.cascade = job.git.cascade or BranchCascade()
    clone_git_repo(job)
    cascade.build(job.git.repo)
    queues = build_queue_collection(job)
    queues.validate()

    # Update the queue status
    job.bert_e.update_queue_status(queues)

    if not queues.mergeable_prs:
        raise exceptions.NothingToDo()

    merge_queues(queues.mergeable_queues)

    # notify PRs and cleanup
    for pr_id in queues.mergeable_prs:
        close_queued_pull_request(job, pr_id, deepcopy(cascade))
        job.bert_e.add_merged_pr(pr_id)

    # git push --all --force --prune
    push(job.git.repo, prune=True)
    raise exceptions.Merged()
