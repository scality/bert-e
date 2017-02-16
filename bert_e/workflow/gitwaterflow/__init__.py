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
"""GitWaterFlow implementation.

This module implements automation of the GitWaterFlow by BertE.

"""
import logging

from bert_e import exceptions as messages
from bert_e.reactor import Reactor, NotFound, NotPrivileged
from bert_e.utils import confirm
from ..git_utils import push, clone_git_repo
from ..pr_utils import find_comment, send_comment, create_task
from .branches import branch_factory, is_cascade_consumer, is_cascade_producer
from .commands import setup, get_active_options  # noqa
from .integration import (create_integration_branches,
                          create_integration_pull_requests,
                          merge_integration_branches,
                          update_integration_branches)
from .jira import jira_checks
from . import queueing


LOG = logging.getLogger(__name__)


def handle_pull_request(job):
    """Analyse and handle a pull request that has just been updated."""
    early_checks(job)
    send_greetings(job)
    handle_comments(job)
    LOG.debug("Running with active options: %r", get_active_options(job))

    src = job.git.src_branch = branch_factory(job.git.repo,
                                              job.pull_request.src_branch)
    dst = job.git.dst_branch = branch_factory(job.git.repo,
                                              job.pull_request.dst_branch)

    check_dependencies(job)

    # Now we're actually going to work on the repository. Let's clone it.
    clone_git_repo(job)

    if job.pull_request.status == 'DECLINED':
        handle_declined_pull_request(job)

    # Handle the case when bitbucket is lagging and the PR was actually
    # merged before.
    if dst.includes_commit(src):
        raise messages.NothingToDo()

    build_branch_cascade(job)
    job.git.cascade.validate()

    check_branch_compatibility(job)
    jira_checks(job)

    # Check source branch still exists
    # (It may have been deleted by developers)
    if not src.exists():
        raise messages.NothingToDo(job.pull_request.src_branch)

    wbranches = list(create_integration_branches(job))
    use_queue = job.settings.use_queue
    if use_queue and queueing.already_in_queue(job, wbranches):
        job.bert_e.handle_merge_queues()

    in_sync = check_in_sync(job, wbranches)

    try:
        update_integration_branches(job, wbranches)
    except:
        raise
    else:
        if job.settings.use_queue and in_sync:
            # In queue mode, in case no conflict is detected,
            # we want to keep the integration branches as they are,
            # hense reset branches to avoid a push later in the code
            for branch in wbranches:
                branch.reset()
    finally:
        # Do not push empty integration branches as this would trigger new
        # builds on the CI server and possibly an overwrite of artifacts, since
        # empty integration w/x.y branches basically point at their target
        # development/x.y branches.
        to_push = [branch for branch in wbranches
                   if branch.get_commit_diff(branch.dst_branch)]
        if to_push:
            push(job.git.repo, to_push)

    child_prs = create_integration_pull_requests(job, wbranches)

    check_pull_request_skew(job, wbranches, child_prs)
    check_approvals(job)
    check_build_status(job, child_prs)

    interactive = job.settings.interactive
    if interactive and not confirm('Do you want to merge/queue?'):
        return

    # If the integration pull requests were already in sync with the
    # feature branch before our last update (which serves as a final
    # check for conflicts), and all builds were green, and we reached
    # this point without an error, then all conditions are met to enter
    # the queue.
    if job.settings.use_queue:
        # validate current state of queues
        try:
            queueing.validate_queues(job)
        except messages.IncoherentQueues as err:
            raise messages.QueueOutOfOrder(
                active_options=get_active_options(job)) from err
        # Enter the merge queue!
        queueing.add_to_queue(job, wbranches)
        job.git.cascade.validate()
        raise messages.Queued(
            branches=job.git.cascade.dst_branches,
            ignored=job.git.cascade.ignored_branches,
            issue=job.git.src_branch.jira_issue_key,
            author=job.pull_request.author_display_name,
            active_options=get_active_options(job))

    else:
        merge_integration_branches(job, wbranches)
        job.bert_e.add_merged_pr(job.pull_request.id)
        job.git.cascade.validate()
        raise messages.SuccessMessage(
            branches=job.git.cascade.dst_branches,
            ignored=job.git.cascade.ignored_branches,
            issue=job.git.src_branch.jira_issue_key,
            author=job.pull_request.author_display_name,
            active_options=get_active_options(job))


def build_branch_cascade(job):
    """Initialize the job's branch cascade."""
    cascade = job.git.cascade
    if cascade.dst_branches:
        # Do not rebuild cascade
        return
    cascade.build(job.git.repo, job.git.dst_branch)
    LOG.debug(cascade.dst_branches)


def early_checks(job):
    """Early checks to filter out pull requests where no action is needed."""
    status = job.pull_request.status
    if status not in ('OPEN', 'DECLINED'):
        raise messages.NothingToDo("The pull request is '{}'".format(status))

    src, dst = job.pull_request.src_branch, job.pull_request.dst_branch

    if not is_cascade_producer(src) or not is_cascade_consumer(dst):
        raise messages.NotMyJob(src, dst)

    if not job.git.repo.remote_branch_exists(dst):
        raise messages.WrongDestination(dst_branch=dst,
                                        active_options=get_active_options(job))


def send_greetings(job):
    """Send welcome message to the pull request's author and set default tasks.

    """
    username = job.settings.robot_username
    if find_comment(job.pull_request, username=username):
        return

    tasks = list(reversed(job.settings.get('tasks', [])))

    comment = send_comment(
        job.settings, job.pull_request, messages.InitMessage(
            bert_e=username, author=job.pull_request.author_display_name,
            status={}, active_options=get_active_options(job), tasks=tasks
        )
    )

    for task in tasks:
        create_task(job.settings, task, comment)


def handle_comments(job):
    """Handle options and commands in the pull request's comments.

    Raises:
        UnknownCommand: if an unrecognized command is sent to BertE.
        NotEnoughCredentials: if the author of a message is trying to set an
                              option or call a command he is not allowed to.

    """
    reactor = Reactor()
    admins = job.settings.admins
    pr_author = job.pull_request.author

    reactor.init_settings(job)

    prefix = '@{}'.format(job.settings.robot_username)
    LOG.debug('looking for prefix: %s', prefix)

    # Handle options
    # Look for options in all of the pull request's comments.
    for comment in job.pull_request.comments:
        author = comment.author
        privileged = author in admins and author != pr_author
        text = comment.text
        try:
            reactor.handle_options(job, text, prefix, privileged)
        except NotFound as err:
            raise messages.UnknownCommand(
                active_options=get_active_options(job), command=err.keyword,
                author=author, comment=text
            ) from err
        except NotPrivileged as err:
            raise messages.NotEnoughCredentials(
                active_options=get_active_options(job), command=err.keyword,
                author=author, self_pr=(author == pr_author), comment=text
            ) from err

    # Handle commands
    # Look for commands in comments posted after BertE's last message.
    for comment in reversed(job.pull_request.comments):
        author = comment.author
        if author == job.settings.robot_username:
            return
        privileged = author in admins and author != pr_author
        text = comment.text
        try:
            reactor.handle_commands(job, text, prefix, privileged)
        except NotFound as err:
            raise messages.UnknownCommand(
                active_options=get_active_options(job), command=err.keyword,
                author=author, comment=text
            ) from err
        except NotPrivileged as err:
            raise messages.NotEnoughCredentials(
                active_options=get_active_options(job), command=err.keyword,
                author=author, self_pr=(author == pr_author), comment=text
            ) from err


def check_branch_compatibility(job):
    """Check that the pull request's source and destination branches are
    compatible with one another.

    For example, check that the user is not trying to merge a new feature
    into any older development/* branch.

    Raises:
        IncompatibleSourceBranchPrefix: if the prefix of the source branch
                                        is incorrect.

    """
    if job.settings.bypass_incompatible_branch:
        return

    src_branch = job.git.src_branch
    for dst_branch in job.git.cascade.dst_branches:
        if src_branch.prefix not in dst_branch.allow_prefixes:
            raise messages.IncompatibleSourceBranchPrefix(
                source=src_branch,
                destination=job.git.dst_branch,
                active_options=get_active_options(job)
            )


def check_dependencies(job):
    """Check the pull request's dependencies, if any.

    Raises:
        AfterPullRequest: if the current pull request depends on other open
                          pull requests to be merged.

    """
    if job.settings.wait:
        raise messages.NothingToDo('wait option is set')

    after_prs = job.settings.after_pull_request

    if not after_prs:
        return

    prs = [job.project_repo.get_pull_request(int(pr_id))
           for pr_id in after_prs]

    opened = [p for p in prs if p.status == 'OPEN']
    merged = [p for p in prs if p.status == 'MERGED']
    declined = [p for p in prs if p.status == 'DECLINED']

    if len(after_prs) != len(merged):
        raise messages.AfterPullRequest(
            opened_prs=opened, declined_prs=declined,
            active_options=get_active_options(job)
        )


def handle_declined_pull_request(job):
    """The pull request was declined.

    Decline integration pull requests and cleanup integration branches.

    Raises:
        PullRequestDeclined: if some cleanup was done.
        NothingToDo: if everything was already clean.

    """
    build_branch_cascade(job)
    changed = False
    src_branch = job.pull_request.src_branch
    dst_branches = job.git.cascade.dst_branches

    wbranch_names = ['w/{}/{}'.format(b.version, src_branch)
                     for b in dst_branches]

    open_prs = list(job.project_repo.get_pull_requests(
        src_branch=wbranch_names, author=job.settings.robot_username
    ))

    for name, dst_branch in zip(wbranch_names, dst_branches):
        for pr in open_prs:
            if (pr.status == 'OPEN' and
                    pr.src_branch == name and
                    pr.dst_branch == dst_branch.name):
                pr.decline()
                changed = True
                break
        wbranch = branch_factory(job.git.repo, name)
        wbranch.src_branch = src_branch
        wbranch.dst_branch = dst_branch
        if wbranch.exists():
            wbranch.remove()
            changed = True

    if changed:
        push(job.git.repo, prune=True)
        raise messages.PullRequestDeclined()
    else:
        raise messages.NothingToDo()


def check_in_sync(job, wbranches) -> bool:
    """Validate that each integration branch contains the last commit from its
    predecessor.

    Returns:
        True: if integration branches are in sync.
        False: otherwise.

    """
    prev = job.git.src_branch
    for branch in wbranches:
        if not branch.includes_commit(prev.get_latest_commit()):
            return False
        prev = branch
    return True


def check_pull_request_skew(job, wbranches, child_prs):
    """Check potential skew between local commit and commit in PR.

    Three cases are possible:
    - the local commit and the commit we obtained in the PR
      object are identical; nothing to do.

    - the local commit, that has just been pushed by Bert-E,
      does not reflect yet in the PR object we obtained from
      bitbucket (the cache mechanism from BB mean the PR is still
      pointing to a previous commit); the solution is to update
      the PR object with the latest commit we know of.

    - the local commit is outdated, someone else has pushed new
      commits on the integration branch, and it reflects in the PR
      object; in this case we abort the process, Bert-E will be
      called again on the new commits.

    Raises:
        PullRequestSkewDetected: if a skew is detected.

    """
    for branch, pull_request in zip(wbranches, child_prs):
        branch_sha1 = branch.get_latest_commit()
        pr_sha1 = pull_request.src_commit  # 12 hex hash
        if branch_sha1.startswith(pr_sha1):
            continue

        if branch.includes_commit(pr_sha1):
            LOG.warning('Skew detected (expected commit: %s, '
                        'got PR commit: %s).', branch_sha1, pr_sha1)
            LOG.warning('Updating the integration PR locally.')
            pull_request.src_commit = branch_sha1
            continue

        raise messages.PullRequestSkewDetected(pull_request.id, branch_sha1,
                                               pr_sha1)


def check_approvals(job):
    """Check approval of a pull request by author, tester and peer.

    Raises:
        - ApprovalRequired
    """
    required_peer_approvals = job.settings.required_peer_approvals
    current_peer_approvals = 0
    if job.settings.bypass_peer_approval:
        current_peer_approvals = required_peer_approvals
    approved_by_author = job.settings.bypass_author_approval
    approved_by_tester = job.settings.bypass_tester_approval
    requires_unanimity = job.settings.unanimity
    is_unanimous = True

    if not job.settings.testers:
        # if the project does not declare any testers,
        # just assume a pseudo-tester has approved the PR
        approved_by_tester = True

    # If a tester is the author of the PR we will bypass
    #  the tester approval
    if job.pull_request.author in job.settings.testers:
        approved_by_tester = True

    if (approved_by_author and
            (current_peer_approvals >= required_peer_approvals) and
            approved_by_tester and not requires_unanimity):
        return

    # NB: when author hasn't approved the PR, author isn't listed in
    # 'participants'
    username = job.settings.robot_username

    participants = set(job.pull_request.get_participants())
    approvals = set(job.pull_request.get_approvals())

    # Exclude Bert-E from consideration
    participants -= {username}

    testers = set(job.settings.testers)

    is_unanimous = approvals - {username} == participants
    approved_by_author |= job.pull_request.author in approvals
    approved_by_tester |= bool(approvals & testers)
    peer_approvals = approvals - testers - {job.pull_request.author}
    current_peer_approvals += len(peer_approvals)
    missing_peer_approvals = (
        required_peer_approvals - current_peer_approvals)

    if not approved_by_author or \
            (testers and not approved_by_tester) or \
            missing_peer_approvals > 0 or \
            (requires_unanimity and not is_unanimous):
        raise messages.ApprovalRequired(
            pr=job.pull_request,
            required_peer_approvals=required_peer_approvals,
            requires_tester_approval=bool(testers),
            requires_unanimity=requires_unanimity,
            active_options=get_active_options(job)
        )


def check_build_status(job, child_prs):
    """Check the build statuses of the integration pull requests.

    Raises:
        BuildFailed: if a build failed or was stopped.
        BuildNotStarted: if a build hasn't started yet.
        BuildInProgress: if a build is still in progress.

    """

    if job.settings.bypass_build_status:
        return

    key = job.settings.build_key
    if not key:
        return

    ordered_state = {
        status: idx for idx, status in enumerate(
            ('SUCCESSFUL', 'INPROGRESS', 'NOTSTARTED', 'STOPPED', 'FAILED'))
    }

    def status(pr):
        return job.project_repo.get_build_status(pr.src_commit, key)

    statuses = {p.src_branch: status(p) for p in child_prs}
    worst = max(child_prs, key=lambda p: ordered_state[statuses[p.src_branch]])
    worst_status = statuses[worst.src_branch]
    if worst_status in ('FAILED', 'STOPPED'):
        raise messages.BuildFailed(pr_id=worst.id,
                                   active_options=get_active_options(job))
    elif worst_status == 'NOTSTARTED':
        raise messages.BuildNotStarted()
    elif worst_status == 'INPROGRESS':
        raise messages.BuildInProgress()
    assert worst_status == 'SUCCESSFUL'
