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
"""GitWaterFlow optimistic queuing implementation."""

import logging
from copy import deepcopy

from bert_e import exceptions
from bert_e.api import git
from bert_e.job import handler as job_handler
from bert_e.job import QueuesJob

from ..git_utils import clone_git_repo, octopus_merge, push
from ..pr_utils import send_comment
from .branches import (BranchCascade, DevelopmentBranch, IntegrationBranch,
                       QueueBranch, QueueCollection, QueueIntegrationBranch,
                       branch_factory)
from .integration import create_integration_branches

LOG = logging.getLogger(__name__)


@job_handler(QueuesJob)
def handle_merge_queues(job):
    """Check merge queue and fast-forward development branches to the most
    recent stable state.

    """
    cascade = job.git.cascade = job.git.cascade or BranchCascade()
    clone_git_repo(job)
    cascade.build(job.git.repo)
    queues = validate_queues(job)

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


def get_queue_branch(job, dev_branch: DevelopmentBranch, create=True
                     ) -> QueueBranch:
    """Get the q/x.y branch corresponding to development/x.y.

    Create it if necessary.

    """
    name = 'q/{}'.format(dev_branch.version)
    qbranch = branch_factory(job.git.repo, name)
    if not qbranch.exists() and create:
        qbranch.create(dev_branch)
    return qbranch


def get_queue_integration_branch(job, pr_id, wbranch: IntegrationBranch
                                 ) -> QueueIntegrationBranch:
    """Get the q/pr_id/x.y/* branch corresponding to a w/x.y/* branch."""
    name = 'q/{}/{}/{}'.format(
        pr_id, wbranch.version, job.pull_request.src_branch
    )
    return branch_factory(job.git.repo, name)


def already_in_queue(job, wbranches):
    """Check if integration branches are already queued for merge.

    Returns:
        True: if the pull request is queued.
        False: otherwise.

    """
    pr_id = job.pull_request.id
    return any(
        get_queue_integration_branch(job, pr_id, w).exists() for w in wbranches
    )


def validate_queues(job):
    """Retrieve the state of the current queue and make sure it is coherent."""
    queues = QueueCollection(job.project_repo, job.settings.build_key,
                             job.git.cascade.get_merge_paths())
    queues.build(job.git.repo)
    queues.validate()
    return queues


def add_to_queue(job, wbranches):
    """Add integration branches into the merge queue.

    Raises:
        QueueConflict: if the pull request is in conflict with content from the
                       queue.

    """
    pr_id = job.pull_request.id
    qbranches = [get_queue_branch(job, w.dst_branch) for w in wbranches]
    to_push = list(qbranches)

    qbranch, *qbranches = qbranches
    wbranch, *wbranches = wbranches

    try:
        qbranch.merge(wbranch)
        qint = get_queue_integration_branch(job, pr_id, wbranch)
        qint.create(qbranch, do_push=False)
        to_push.append(qint)
        for qbranch, wbranch in zip(qbranches, wbranches):
            octopus_merge(qbranch, wbranch, qint)
            qint = get_queue_integration_branch(job, pr_id, wbranch)
            qint.create(qbranch, do_push=False)
            to_push.append(qint)
    except git.MergeFailedException as err:
        raise exceptions.QueueConflict(
            active_options=job.active_options) from err

    push(job.git.repo, to_push)


def merge_queues(queues):
    """Fast-forward the development branches to the most recent mergeable
    queued pull request and delete the merged queue-integration branches.

    """
    for branches in queues.values():
        # Fast-forward development/x.y to the most recent mergeable queue
        destination = branches[QueueBranch].dst_branch
        if branches[QueueIntegrationBranch]:
            latest = branches[QueueIntegrationBranch][0]
            LOG.debug("Merging %s into %s", latest, destination)
            destination.merge(latest)

            # Delete the merged queue-integration branches
            for queue in branches[QueueIntegrationBranch]:
                LOG.debug("Removing %s", queue)
                queue.remove()


def close_queued_pull_request(job, pr_id, cascade):
    """Close queued pull requests that have been merged."""
    job.git.cascade = cascade
    repo = job.git.repo
    pull_request = job.project_repo.get_pull_request(int(pr_id))
    src = job.git.src_branch = branch_factory(repo, pull_request.src_branch)
    dst = job.git.dst_branch = branch_factory(repo, pull_request.dst_branch)
    job.git.cascade.finalize(dst)

    if dst.includes_commit(src.get_latest_commit()):
        # Everything went fine, send a success message
        send_comment(
            job.settings, pull_request, exceptions.SuccessMessage(
                branches=job.git.cascade.dst_branches,
                ignored=job.git.cascade.ignored_branches,
                issue=src.jira_issue_key,
                author=pull_request.author_display_name,
                active_options=[])
        )

    else:
        # Frown at the author for adding posterior changes. This
        # message will wake Bert-E up on the Pull Request, and the queues
        # have disappeared, so the normal pre-queuing workflow will restart
        # naturally.
        commits = list(src.get_commit_diff(dst))
        send_comment(
            job.settings, pull_request, exceptions.PartialMerge(
                commits=commits, branches=job.git.cascade.dst_branches,
                active_options=[])
        )

    # Remove integration branches (potentially let Bert-E rebuild them if
    # the merge was partial)
    wbranches = list(create_integration_branches(job))

    # Checkout destination branch so we are not on a w/* branch when
    # deleting it.
    dst.checkout()
    for wbranch in wbranches:
        try:
            wbranch.remove()
        except git.RemoveFailedException:
            # not critical
            pass
