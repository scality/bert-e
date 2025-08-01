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
from bert_e.job import APIJob, handler
from bert_e.lib.simplecmd import CommandError
from bert_e.lib.git import RemoveFailedException
from bert_e.workflow.git_utils import clone_git_repo
from bert_e.workflow.gitwaterflow.branches import (DevelopmentBranch,
                                                   HotfixBranch,
                                                   build_queue_collection,
                                                   QueueBranch,
                                                   branch_factory)

LOG = logging.getLogger(__name__)


class DeleteBranchJob(APIJob):
    """Job that will delete a destination branch."""
    @property
    def url(self) -> str:
        return ''

    def __str__(self):
        return 'Delete destination branch %r' % self.settings.branch


def do_delete(branch, force=False):
    try:
        if branch.exists():
            branch.remove(del_local=False, force=force, do_push=True)
    except RemoveFailedException:
        raise exceptions.JobFailure('Unable to delete branch on repository, '
                                    'please check branch permissions.')


@handler(DeleteBranchJob)
def delete_branch(job: DeleteBranchJob):
    """Delete a destination branch."""

    repo = clone_git_repo(job)

    # do sanity check of branch name
    try:
        del_branch = branch_factory(repo, job.settings.branch)
    except exceptions.UnrecognizedBranchPattern:
        raise exceptions.JobFailure('Requested branch %r is not a '
                                    'GWF branch.' % job.settings.branch)

    if not (isinstance(del_branch, DevelopmentBranch) or
            isinstance(del_branch, HotfixBranch)):
        raise exceptions.JobFailure('Requested branch %r is not a GWF '
                                    'destination branch.' % del_branch)

    # if branch does not exist, do nothing
    if job.settings.branch not in repo.remote_branches:
        raise exceptions.NothingToDo()

    # do not allow deleting a branch if the archive tag is already there
    if not isinstance(del_branch, HotfixBranch) and \
       del_branch.version in repo.cmd('git tag').split('\n')[:-1]:
        raise exceptions.JobFailure('Cannot delete branch %r because there is '
                                    'already an archive tag %r in the '
                                    'repository.' %
                                    (del_branch, del_branch.version))

    if job.settings.use_queue:
        queue_collection = build_queue_collection(job)
        if queue_collection.has_version_queued_prs(del_branch.version_t):
            raise exceptions.JobFailure('Requested branch %r cannot be '
                                        'deleted now due to queued data.' %
                                        del_branch)

        # delete local q branch
        del_queue = QueueBranch(repo, 'q/%s' % del_branch.version)
        do_delete(del_queue)

    archive_tag = del_branch.version
    if isinstance(del_branch, HotfixBranch):
        archive_tag = archive_tag + '.archived_hotfix_branch'
    try:
        del_branch.checkout()
        repo.cmd('git tag %s' % archive_tag)
        repo.cmd('git push origin %s' % archive_tag)
    except CommandError:
        raise exceptions.JobFailure('Unable to push new tag, '
                                    'keep pushing.')

    do_delete(del_branch, force=True)

    raise exceptions.JobSuccess()
