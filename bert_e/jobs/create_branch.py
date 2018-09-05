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
from bert_e.workflow.git_utils import clone_git_repo, push
from bert_e.workflow.gitwaterflow.branches import (BranchCascade,
                                                   DevelopmentBranch,
                                                   StabilizationBranch,
                                                   build_queue_collection,
                                                   branch_factory)

from .rebuild_queues import RebuildQueuesJob

LOG = logging.getLogger(__name__)


class CreateBranchJob(APIJob):
    """Job that will create a new destination branch."""
    @property
    def url(self) -> str:
        return ''

    def __str__(self):
        return 'Create destination branch %r' % self.settings.branch


@handler(CreateBranchJob)
def create_branch(job: CreateBranchJob):
    """Create a new destination branch."""

    repo = clone_git_repo(job)

    # if branch already is there, do nothing
    if job.settings.branch in repo.remote_branches:
        raise exceptions.NothingToDo()

    # do sanity check of new branch name
    try:
        new_branch = branch_factory(repo, job.settings.branch)
    except exceptions.UnrecognizedBranchPattern:
        raise exceptions.JobFailure('Requested new branch %r is not a '
                                    'GWF branch.' % job.settings.branch)

    if not (isinstance(new_branch, DevelopmentBranch) or
            isinstance(new_branch, StabilizationBranch)):
        raise exceptions.JobFailure('Requested new branch %r is not a GWF '
                                    'destination branch.' % new_branch)

    # do not allow recreating a previously existing identical branch
    # (unless archive tag is manually removed)
    if new_branch.version in repo.cmd('git tag').split('\n')[:-1]:
        raise exceptions.JobFailure('Cannot create branch %r because there is '
                                    'already an archive tag %r in the '
                                    'repository.' %
                                    (new_branch, new_branch.version))

    cascade = BranchCascade()
    cascade.build(job.git.repo)
    dev_branches = cascade.get_development_branches()

    # sanity check provided branching point...
    if 'branch_from' in job.settings and job.settings['branch_from']:
        if not dev_branches[-1].includes_commit(job.settings.branch_from):
            raise exceptions.JobFailure('Provided branching point %r is not '
                                        'included in latest development '
                                        'branch.' % job.settings.branch_from)
    # ...or determine the branching point automatically
    else:
        if isinstance(new_branch, StabilizationBranch):
            job.settings.branch_from = DevelopmentBranch(
                repo,
                'development/%s.%s' % (new_branch.major, new_branch.minor))

            if job.settings.branch_from not in dev_branches:
                raise exceptions.JobFailure('Cannot create a stabilization '
                                            'branch %r without a supporting '
                                            'development branch ' %
                                            new_branch)

        else:
            job.settings.branch_from = dev_branches[0]
            for dev_branch in dev_branches:
                if new_branch > dev_branch:
                    job.settings.branch_from = dev_branch

    # do not allow creation of older dev branches if queue work is pending
    # (it would force prs in queue to create new intermediary /w branches
    # and require the author to restart conflict resolutions);
    #
    # only allow newest dev branches if queues are in progress; queued pull
    # requests will create additional /w branches, but this will not trigger
    # any new conflict.
    #
    # older dev branches can be created if queues are disabled, or empty.
    #
    # there are no restrictions for stabilization branches.
    if (job.settings.use_queue and
            not isinstance(new_branch, StabilizationBranch) and
            new_branch < dev_branches[-1]):
        queue_collection = build_queue_collection(job)
        if queue_collection.queued_prs:
            raise exceptions.JobFailure('Requested new branch %r cannot be '
                                        'created now due to queued data.' %
                                        new_branch)

    # create branch locally and check cascade state
    new_branch.create(job.settings.branch_from, do_push=False)
    try:
        new_cascade = BranchCascade()
        new_cascade.build(job.git.repo)
        new_cascade.validate()
    except exceptions.BertE_Exception as excp:
        raise exceptions.JobFailure('Requested new branch %r does not '
                                    'conform to GWF rules (%s)' %
                                    (new_branch, excp.__class__.__name__))

    try:
        push(repo, branches=[new_branch])
    except CommandError:
        raise exceptions.JobFailure('Unable to push new branch, '
                                    'keep pushing.')

    if (not job.settings.use_queue or
            isinstance(new_branch, StabilizationBranch)):
        raise exceptions.JobSuccess()

    next_job = RebuildQueuesJob(bert_e=job.bert_e)
    job.bert_e.process(next_job)
    # next_job will raise JobSuccess for us.
