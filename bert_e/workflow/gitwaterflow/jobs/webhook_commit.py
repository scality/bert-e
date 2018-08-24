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

from bert_e import exceptions
from bert_e.job import handler, CommitJob, PullRequestJob

from .evaluate_queues import QueuesJob
from ..branches import branch_factory, QueueBranch, IntegrationBranch


@handler(CommitJob)
def handle_webhook_commit(job: CommitJob):
    """Handle a job triggered by an updated build status."""
    candidates = [
        branch_factory(job.git.repo, b)
        for b in job.git.repo.get_branches_from_commit(job.commit)
    ]

    if not candidates:
        raise exceptions.NothingToDo(
            'Could not find any branch for commit {}' .format(job.commit)
        )

    if job.settings.use_queue:
        if any(isinstance(b, QueueBranch) for b in candidates):
            return job.bert_e.process(QueuesJob(bert_e=job.bert_e))

    def get_parent_branch(branch):
        if isinstance(branch, IntegrationBranch):
            return branch.feature_branch
        else:
            return branch.name

    candidates = list(map(get_parent_branch, candidates))

    prs = list(
        job.project_repo.get_pull_requests(src_branch=candidates)
    )
    if not prs:
        raise exceptions.NothingToDo(
            'Could not find the main pull request for commit {}' .format(
                job.commit)
        )
    pr = min(prs, key=lambda pr: pr.id)

    return job.bert_e.process(
        PullRequestJob(
            bert_e=job.bert_e,
            pull_request=job.project_repo.get_pull_request(int(pr.id))
        )
    )
