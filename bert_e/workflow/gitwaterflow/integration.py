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
from bert_e.lib import git

from ..git_utils import consecutive_merge, robust_merge, push
from ..pr_utils import send_comment
from .branches import (branch_factory, build_branch_cascade,
                       GhostIntegrationBranch)


def get_integration_branches(job):
    """Get existing integration branches created by the robot."""
    build_branch_cascade(job)  # Does nothing if the cascade already exists
    src = job.git.src_branch
    for dst in job.git.cascade.dst_branches:
        name = "w/{}/{}".format(dst.version, src)
        branch = branch_factory(job.git.repo, name)
        branch.src_branch, branch.dst_branch = src, dst
        if branch.exists():
            yield branch


def create_integration_branches(job):
    """Create integration branches if they do not exist."""
    build_branch_cascade(job)
    src = job.git.src_branch
    branch = GhostIntegrationBranch(job.git.src_branch.repo,
                                    job.git.src_branch.name,
                                    job.git.dst_branch)
    branch.src_branch, branch.dst_branch = src, job.git.cascade.dst_branches[0]
    yield branch
    for dst in job.git.cascade.dst_branches[1:]:
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
    feature_branch, *children = wbranches

    # Check for history mismatch. If a merge commit comes neither from the dev
    # branch nor from the original feature branch, it likely means the feature
    # branch has been rebased
    prev = feature_branch
    for wbranch in children:
        prev_set = set(prev.get_commit_diff(prev.dst_branch, False))
        dst_set = set(
            wbranch.dst_branch.get_commit_diff(prev.dst_branch, False)
        )
        wbranch_set = set(
            wbranch.get_commit_diff(wbranch.dst_branch, False)
        ) - prev_set

        # Special case: detect branch reset to prior commit
        # Any non-merge commit on the wbranch must have been made from a
        # previous commit of this wbranch. If the parent doesn't belong to the
        # wbranch, then we are in trouble.
        for rev in wbranch_set:
            if rev.is_merge or rev.parents[0] in wbranch_set:
                continue
            raise exceptions.BranchHistoryMismatch(
                integration_branch=wbranch, feature_branch=feature_branch,
                development_branch=wbranch.dst_branch, commit=rev,
                active_options=job.active_options
            )

        # Broader case. All commits on the integration branch must have its
        # parents from:
        # * the wbranch,
        # * the previous integration branch,
        # * the target development branch.
        acceptable_parents = prev_set | dst_set | wbranch_set
        for rev in wbranch_set:
            if not all(p in acceptable_parents for p in rev.parents):
                raise exceptions.BranchHistoryMismatch(
                    integration_branch=wbranch, feature_branch=feature_branch,
                    development_branch=wbranch.dst_branch, commit=rev,
                    active_options=job.active_options
                )
        prev = wbranch

    def update(wbranch, source):
        empty = not list(wbranch.get_commit_diff(wbranch.dst_branch))
        try:
            if job.settings.no_octopus:
                consecutive_merge(wbranch, wbranch.dst_branch, source)
            else:
                robust_merge(wbranch, wbranch.dst_branch, source)
        except git.MergeFailedException as err:
            raise exceptions.Conflict(
                source=source, wbranch=wbranch, dev_branch=job.git.dst_branch,
                feature_branch=job.git.src_branch, origin=False, empty=empty,
                active_options=job.active_options
            ) from err

    prev = feature_branch

    # Explicitely check conflicts between the feature branch and its
    # destination
    check_conflict(job, prev.dst_branch, prev)

    for idx, branch in enumerate(children):
        update(branch, prev)
        prev = branch


def check_conflict(job, dst: git.Branch, src: git.Branch):
    """Check conflict between the source and destination branches of a PR."""
    # Create a temporary branch starting off from the destination branch, only
    # to check for conflicts
    wtmp = git.Branch(job.git.repo, 'w/{}'.format(dst))
    try:
        wtmp.create(dst, do_push=False)
        wtmp.merge(src)
    except git.MergeFailedException as err:
        wtmp.reset(False, False)
        raise exceptions.Conflict(
            source=src, wbranch=src, dev_branch=dst, feature_branch=src,
            origin=True, empty=False, active_options=job.active_options
        ) from err
    finally:
        dst.checkout()
        wtmp.remove()


def create_integration_pull_requests(job, wbranches):
    """Create integration pull requests if they do not exist."""

    if (job.settings.always_create_integration_pull_requests is False and
            job.settings.create_pull_requests is False):
        return []

    # read open PRs and store them for multiple usage
    wbranch_names = [wbranch.name for wbranch in wbranches]
    open_prs = [
        pr for pr in job.project_repo.get_pull_requests(
            src_branch=wbranch_names
        ) if pr.status == 'OPEN']

    prs = []
    for wbranch in wbranches:
        # FIXME: git branches shouldn't be allowed to interact to create
        # pull requests: that's an undesirable coupling.
        pr, created = wbranch.get_or_create_pull_request(
            job.pull_request, open_prs, job.project_repo
        )
        setattr(pr, 'newly_created', created)
        prs.append(pr)

    return prs


def notify_integration_data(job, wbranches, child_prs):
    if len(wbranches) > 1:
        send_comment(
            job.settings, job.pull_request,
            exceptions.IntegrationDataCreated(
                bert_e=job.settings.robot_username,
                pr=job.pull_request,
                wbranches=wbranches,
                child_prs=child_prs,
                ignored=job.git.cascade.ignored_branches,
                active_options=job.active_options,
                owner=job.settings.repository_owner,
                githost=job.settings.repository_host,
                slug=job.settings.repository_slug
            )
        )


def merge_integration_branches(job, wbranches):
    """Merge integration branches into their target development branches."""
    first, *children = wbranches
    first.dst_branch.merge(first)
    prev = first
    for wbranch in children:
        # The octopus merge makes sure that the merge leaves the development
        # branches self-contained.
        if job.settings.no_octopus:
            consecutive_merge(wbranch.dst_branch, prev.dst_branch, wbranch)
        else:
            robust_merge(wbranch.dst_branch, prev.dst_branch, wbranch)
        prev = wbranch

    for wbranch in children:
        try:
            wbranch.remove()
        except git.RemoveFailedException:
            # ignore failures as this is non critical
            pass

    push(job.git.repo, prune=True)
