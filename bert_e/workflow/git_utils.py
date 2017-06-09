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
"""Git utility functions."""
import logging

from bert_e.lib import git
from bert_e.lib.retry import RetryHandler

LOG = logging.getLogger(__name__)


def robust_merge(dst: git.Branch, src1: git.Branch, src2: git.Branch):
    """'Best-effort' octopus merge.

    Perform both the merge using octopus and consecutive strategies.
    If the resulting branches differ, keep the result of consecutive merges.
    Otherwise, keep the octopus merge.

    """
    tmp_oct = git.Branch(dst.repo, 'tmp/octopus/{}'.format(dst))
    tmp_cns = git.Branch(dst.repo, 'tmp/normal/{}'.format(dst))

    tmp_oct.create(dst, do_push=False)
    tmp_cns.create(dst, do_push=False)

    oct_conflict = None

    try:
        octopus_merge(tmp_oct, src1, src2)
    except git.MergeFailedException as err:
        oct_conflict = err

    consecutive_merge(tmp_cns, src1, src2)

    if oct_conflict is not None:
        dst.merge(tmp_cns)
    elif tmp_cns.differs(tmp_oct):
        LOG.warning('Octopus merge yielded a different result than consecutive'
                    ' merges.')
        dst.merge(tmp_cns)
    else:
        dst.merge(tmp_oct)

    tmp_oct.remove()
    tmp_cns.remove()


def octopus_merge(dst: git.Branch, src1: git.Branch, src2: git.Branch):
    """Try a 3-way octopus merge.

    If it fails, try merging sources in opposite order.
    If it still fails try a poor man's 3-way merge by doing two consecutive
    2-way merges.

    Raises:
        git.MergeFailedException: if there is an actual conflict.

    """
    try:
        dst.merge(src1, src2)
    except git.MergeFailedException as err:
        try:
            dst.reset(False, False)
            dst.merge(src2, src1)
        except git.MergeFailedException:
            dst.reset(False, False)
            raise err
        except Exception:
            raise err


def consecutive_merge(dst: git.Branch, src1: git.Branch, src2: git.Branch):
    """Poor man's 3-way merge using two consecutive 2-way merges.

    If it fails, try merging sources in opposite order.

    Raises:
        git.MergeFailedException: if there is an actual conflict.

    """
    try:
        dst.merge(src1)
        dst.merge(src2)
    except git.MergeFailedException as err:
        try:
            dst.reset(False, False)
            dst.merge(src2)
            dst.merge(src1)
        except git.MergeFailedException:
            raise
        except Exception:
            raise err


def push(repo: git.Repository, branches=(), prune=False):
    """Push multiple branches at once. Retry up to 30 seconds before giving up.

    Args:
        repo: Git repository to push.
        branches: branches to push.
        prune: push branch deletions too.

    """
    retry = RetryHandler(30, LOG)
    names = ''
    if branches:
        names = ' '.join("'{0}'".format(b.name) for b in branches)
        with retry:
            retry.run(
                repo.push, names,
                catch=git.PushFailedException,
                fail_msg="Failed to push changes"
            )
    else:
        with retry:
            retry.run(
                repo.push_all,
                prune=prune,
                catch=git.PushFailedException,
                fail_msg="Failed to push changes"
            )


def clone_git_repo(job):
    """Get a local clone of the project's repository to work on."""
    repo = job.git.repo
    repo.clone()
    repo.config('user.email', job.settings.robot_email)
    repo.config('user.name', job.settings.robot_username)
    repo.config('merge.renameLimit', '999999')
    return repo
