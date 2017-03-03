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
"""This module holds functions used to interact with the integration branch
cascade.

Those functions are both needed by the 'bare' GitWaterFlow and the queueing
extension.

"""
from bert_e import exceptions
from bert_e.api import git

from ..git_utils import octopus_merge, push
from ..pr_utils import send_comment
from .branches import branch_factory


def create_integration_branches(job):
    """Create integration branches if they do not exist."""
    src = job.git.src_branch
    for dst in job.git.cascade.dst_branches:
        name = "w/{}/{}".format(dst.version, src)
        branch = branch_factory(job.git.repo, name)
        branch.src_branch, branch.dst_branch = src, dst
        if not branch.exists():
            branch.create(dst, do_push=False)
        yield branch


def update_integration_branches(job, wbranches):
    """Update integration branches by merging the pull request's source branch
    down the integration cascade.

    Raises:
        BranchHistoryMismatch: if the first integration branch contains a
                               commit that comes neither from its source nor
                               its destination branch.
        Conflict: if a conflict is detected during the update.

    """
    prev, *children = wbranches
    # Check that the first integration branch contains commits from its
    # source and destination branch only.
    src, dst = prev.src_branch, prev.dst_branch

    # Always get new commits compared to the destination (i.e. obtain the list
    # of commits from the source branch), because the destination may grow very
    # fast during the lifetime of the source branch. A long list is very slow
    # to process due to the loop.
    for commit in prev.get_commit_diff(dst):
        if not src.includes_commit(commit):
            raise exceptions.BranchHistoryMismatch(
                commit=commit, integration_branch=prev, feature_branch=src,
                development_branch=dst, active_options=job.active_options
            )

    def update(wbranch, source, origin=False):
        empty = not wbranch.get_commit_diff(wbranch.dst_branch)
        try:
            octopus_merge(wbranch, wbranch.dst_branch, source)
        except git.MergeFailedException as err:
            raise exceptions.Conflict(
                source=source, wbranch=wbranch, dev_branch=job.git.dst_branch,
                feature_branch=job.git.src_branch, origin=origin, empty=empty,
                active_options=job.active_options
            ) from err

    update(prev, job.git.src_branch, True)
    for branch in children:
        update(branch, prev)
        prev = branch


def create_integration_pull_requests(job, wbranches):
    """Create integration pull requests if they do not exist."""
    # read open PRs and store them for multiple usage
    wbranch_names = [wbranch.name for wbranch in wbranches]
    open_prs = list(
        pr for pr in job.project_repo.get_pull_requests(
            src_branch=wbranch_names,
            author=job.settings.robot_username
        ) if pr.status == 'OPEN')
    prs, created = zip(*(
        # FIXME: git branches shouldn't be allowed to interact to create
        # pull requests: that's an undesirable coupling.
        wbranch.get_or_create_pull_request(
            job.pull_request, open_prs, job.project_repo, idx == 0
        )
        for idx, wbranch in enumerate(wbranches)
    ))
    if any(created):
        send_comment(
            job.settings, job.pull_request,
            exceptions.IntegrationPullRequestsCreated(
                bert_e=job.settings.robot_username, pr=job.pull_request,
                child_prs=prs, ignored=job.git.cascade.ignored_branches,
                active_options=job.active_options
            )
        )
    return prs


def merge_integration_branches(job, wbranches):
    """Merge integration branches into their target development branches."""
    for wbranch in wbranches:
        wbranch.dst_branch.merge(wbranch, force_commit=False)

    for wbranch in wbranches:
        try:
            wbranch.remove()
        except git.RemoveFailedException:
            # ignore failures as this is non critical
            pass

    push(job.git.repo, prune=True)
