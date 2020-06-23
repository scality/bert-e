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
"""GitWaterFlow implementation.

This module implements automation of the GitWaterFlow by BertE.

"""
import logging
import re

from bert_e import exceptions as messages
from bert_e.job import handler, CommitJob, PullRequestJob, QueuesJob
from bert_e.lib.cli import confirm
from bert_e.reactor import Reactor, NotFound, NotPrivileged, NotAuthored
from ..git_utils import push, clone_git_repo
from ..pr_utils import find_comment, send_comment, create_task
from .branches import (
    branch_factory, build_branch_cascade, is_cascade_consumer,
    is_cascade_producer, BranchCascade, QueueBranch, IntegrationBranch
)
from .commands import setup  # noqa
from .integration import (create_integration_branches,
                          create_integration_pull_requests,
                          merge_integration_branches,
                          notify_integration_data,
                          update_integration_branches)
from .jira import jira_checks
from . import queueing


LOG = logging.getLogger(__name__)


@handler(PullRequestJob)
def handle_pull_request(job: PullRequestJob):
    """Analyse and handle a pull request that has just been updated."""
    if job.pull_request.author == job.settings.robot:
        return handle_parent_pull_request(job, job.pull_request)
    try:
        _handle_pull_request(job)
    except messages.TemplateException as err:
        send_comment(job.settings, job.pull_request, err)
        raise


@handler(CommitJob)
def handle_commit(job: CommitJob):
    """Handle a job triggered by an updated build status."""
    candidates = [
        branch_factory(job.git.repo, b)
        for b in job.git.repo.get_branches_from_commit(job.commit)
    ]

    if not candidates:
        raise messages.NothingToDo(
            'Could not find any branch for commit {}' .format(job.commit)
        )

    if job.settings.use_queue:
        if any(isinstance(b, QueueBranch) for b in candidates):
            return queueing.handle_merge_queues(QueuesJob(bert_e=job.bert_e))

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
        raise messages.NothingToDo(
            'Could not find the main pull request for commit {}' .format(
                job.commit)
        )
    pr = min(prs, key=lambda pr: pr.id)

    return handle_pull_request(
        PullRequestJob(
            bert_e=job.bert_e,
            pull_request=job.project_repo.get_pull_request(int(pr.id))
        )
    )


def handle_parent_pull_request(job, child_pr, is_child=True):
    """Handle the parent of an integration pull request."""
    if is_child:
        ids = re.findall('\d+', child_pr.description)
        if not ids:
            raise messages.ParentPullRequestNotFound(child_pr.id)
        parent_id, *_ = ids
    else:
        parent_id = child_pr.id
    return handle_pull_request(
        PullRequestJob(
            bert_e=job.bert_e,
            pull_request=job.project_repo.get_pull_request(int(parent_id))
        )
    )


def _handle_pull_request(job: PullRequestJob):
    job.git.cascade = job.git.cascade or BranchCascade()
    early_checks(job)
    send_greetings(job)
    src = job.git.src_branch = branch_factory(job.git.repo,
                                              job.pull_request.src_branch)
    dst = job.git.dst_branch = branch_factory(job.git.repo,
                                              job.pull_request.dst_branch)

    handle_comments(job)
    LOG.debug("Running with active options: %r", job.active_options)

    check_dependencies(job)

    # Now we're actually going to work on the repository. Let's clone it.
    clone_git_repo(job)

    if job.pull_request.status == 'DECLINED':
        handle_declined_pull_request(job)

    # Handle the case when bitbucket is lagging and the PR was actually
    # merged before.
    if dst.includes_commit(src):
        raise messages.NothingToDo()

    # Reject PRs that are too old
    check_commit_diff(job)

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
        queueing.handle_merge_queues(QueuesJob(bert_e=job.bert_e))

    in_sync = check_in_sync(job, wbranches)

    try:
        update_integration_branches(job, wbranches)
    except messages.Conflict as ex:
        # When a conflict arise on a wbranch, only push the first wbranches up
        # to (and not including) the conflicting one
        push(job.git.repo, wbranches[1:wbranches.index(ex.kwargs['wbranch'])])
        raise
    except Exception:
        raise
    else:
        if job.settings.use_queue and in_sync:
            # In queue mode, in case no conflict is detected,
            # we want to keep the integration branches as they are,
            # hence reset branches to avoid a push later in the code
            for branch in wbranches:
                branch.reset(ignore_missing=True)
        push(job.git.repo, wbranches[1:])

    # create integration pull requests (if requested)
    child_prs = create_integration_pull_requests(job, wbranches)

    if child_prs:
        check_pull_request_skew(job, wbranches, child_prs)

    if (any(wbranch.newly_created for wbranch in wbranches) or
            any(child_pr.newly_created for child_pr in child_prs)):
        notify_integration_data(job, wbranches, child_prs)

    check_approvals(job)
    check_build_status(job, wbranches)

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
            queues = queueing.build_queue_collection(job)
            queues.validate()
        except messages.IncoherentQueues as err:
            raise messages.QueueOutOfOrder(
                active_options=job.active_options) from err
        # Enter the merge queue!
        queueing.add_to_queue(job, wbranches)
        job.git.cascade.validate()
        raise messages.Queued(
            branches=job.git.cascade.dst_branches,
            ignored=job.git.cascade.ignored_branches,
            issue=job.git.src_branch.jira_issue_key,
            author=job.pull_request.author_display_name,
            active_options=job.active_options)

    else:
        merge_integration_branches(job, wbranches)
        job.bert_e.add_merged_pr(job.pull_request.id)
        job.git.cascade.validate()
        raise messages.SuccessMessage(
            branches=job.git.cascade.dst_branches,
            ignored=job.git.cascade.ignored_branches,
            issue=job.git.src_branch.jira_issue_key,
            author=job.pull_request.author_display_name,
            active_options=job.active_options)


def early_checks(job):
    """Early checks to filter out pull requests where no action is needed."""
    status = job.pull_request.status
    if status not in ('OPEN', 'DECLINED'):
        raise messages.NothingToDo("The pull request is '{}'".format(status))

    src, dst = job.pull_request.src_branch, job.pull_request.dst_branch

    if (not is_cascade_producer(src) or not is_cascade_consumer(dst)) and \
       not dst.startswith('hotfix/'):
        raise messages.NotMyJob(src, dst)

    if not job.git.repo.remote_branch_exists(dst):
        raise messages.WrongDestination(dst_branch=dst,
                                        active_options=job.active_options)


def send_greetings(job):
    """Send welcome message to the pull request's author and set default tasks.

    """
    username = job.settings.robot
    if find_comment(job.pull_request, username=username):
        return

    tasks = list(reversed(job.settings.tasks))

    comment = send_comment(
        job.settings, job.pull_request, messages.InitMessage(
            bert_e=username, author=job.pull_request.author_display_name,
            status={}, active_options=job.active_options, tasks=tasks,
            frontend_url=job.bert_e.settings.frontend_url
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

    prefix = '@{}'.format(job.settings.robot)
    LOG.debug('looking for prefix: %s', prefix)

    # Handle options
    # Look for options in all of the pull request's comments.
    for comment in job.pull_request.comments:
        author = comment.author
        privileged = author in admins and author != pr_author
        authored = author == pr_author
        text = comment.text
        try:
            reactor.handle_options(job, text, prefix, privileged, authored)
        except NotFound as err:
            raise messages.UnknownCommand(
                active_options=job.active_options, command=err.keyword,
                author=author, comment=text
            ) from err
        except NotPrivileged as err:
            raise messages.NotEnoughCredentials(
                active_options=job.active_options, command=err.keyword,
                author=author, self_pr=(author == pr_author), comment=text
            ) from err
        except NotAuthored as err:
            raise messages.NotAuthor(
                active_options=job.active_options, command=err.keyword,
                author=author, pr_author=pr_author, authored=authored
            ) from err
        except TypeError as err:
            raise messages.IncorrectCommandSyntax(
                extra_message=str(err), active_options=job.active_options
            ) from err

    # Handle commands
    # Look for commands in comments posted after BertE's last message.
    for comment in reversed(job.pull_request.comments):
        author = comment.author
        if author == job.settings.robot:
            return
        privileged = author in admins and author != pr_author
        text = comment.text
        try:
            reactor.handle_commands(job, text, prefix, privileged)
        except NotFound as err:
            raise messages.UnknownCommand(
                active_options=job.active_options, command=err.keyword,
                author=author, comment=text
            ) from err
        except NotPrivileged as err:
            raise messages.NotEnoughCredentials(
                active_options=job.active_options, command=err.keyword,
                author=author, self_pr=(author == pr_author), comment=text
            ) from err


def check_commit_diff(job):
    """Check for divergence between a PR's source and destination branches.

    raises:
        SourceBranchTooOld: if the branches have diverged.

    """
    threshold = job.settings.max_commit_diff
    LOG.debug('max_commit_diff: %d', job.settings.max_commit_diff)
    if threshold < 1:
        # Feature is deactivated (default)
        return

    commits = list(job.git.dst_branch.get_commit_diff(job.git.src_branch))
    LOG.debug('commit_diff: %d', len(commits))
    if len(commits) > threshold:
        raise messages.SourceBranchTooOld(
            src_branch=job.git.src_branch.name,
            dst_branch=job.git.dst_branch.name,
            threshold=threshold,
            active_options=job.active_options
        )


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
                active_options=job.active_options
            )


def check_dependencies(job):
    """Check the pull request's dependencies, if any.

    Raises:
        AfterPullRequest: if the current pull request depends on other open
                          pull requests to be merged.
        NothingToDo: if the wait option is set then nothing will be checked.


    """
    if job.settings.wait:
        raise messages.NothingToDo('wait option is set')

    after_prs = job.settings.after_pull_request

    if not after_prs:
        return

    prs = []
    for pr_id in after_prs:
        try:
            prs.append(job.project_repo.get_pull_request(int(pr_id)))
        except Exception as err:
            raise messages.IncorrectPullRequestNumber(
                pr_id=pr_id, active_options=job.active_options
            ) from err

        opened = [p for p in prs if p.status == 'OPEN']
        merged = [p for p in prs if p.status == 'MERGED']
        declined = [p for p in prs if p.status == 'DECLINED']

    if len(after_prs) != len(merged):
        raise messages.AfterPullRequest(
            opened_prs=opened, declined_prs=declined,
            active_options=job.active_options
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

    open_prs = list(
        job.project_repo.get_pull_requests(src_branch=wbranch_names)
    )

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
    """Check approval of a pull request by author, peers, and leaders.

    Raises:
        - ApprovalRequired
    """
    required_peer_approvals = job.settings.required_peer_approvals
    current_peer_approvals = 0
    if job.settings.bypass_peer_approval:
        current_peer_approvals = required_peer_approvals

    required_leader_approvals = job.settings.required_leader_approvals
    current_leader_approvals = 0
    if job.settings.bypass_leader_approval:
        current_leader_approvals = required_leader_approvals

    approved_by_author = (not job.settings.need_author_approval or
                          job.settings.bypass_author_approval or
                          job.settings.approve)
    requires_unanimity = job.settings.unanimity
    is_unanimous = True

    if (approved_by_author and
            (current_peer_approvals >= required_peer_approvals) and
            (current_leader_approvals >= required_leader_approvals) and
            not requires_unanimity):
        return

    # NB: when author hasn't approved the PR, author isn't listed in
    # 'participants'
    username = job.settings.robot

    participants = set(job.pull_request.get_participants())
    approvals = set(job.pull_request.get_approvals())
    if job.settings.approve:
        approvals.add(job.pull_request.author)

    # Exclude Bert-E from consideration
    participants -= {username}

    leaders = set(job.settings.project_leaders)

    is_unanimous = approvals - {username} == participants
    approved_by_author |= job.pull_request.author in approvals
    current_leader_approvals += len(approvals.intersection(leaders))
    if (job.pull_request.author in leaders and
            job.pull_request.author not in approvals):
        # if a project leader creates a PR and has not approved it
        # (which is not possible on Github for example), always count
        # one additional mandatory approval
        current_leader_approvals += 1
    missing_leader_approvals = (
        required_leader_approvals - current_leader_approvals)
    peer_approvals = approvals - {job.pull_request.author}
    current_peer_approvals += len(peer_approvals)
    missing_peer_approvals = (
        required_peer_approvals - current_peer_approvals)

    change_requests = set(job.pull_request.get_change_requests())

    LOG.info('approvals: %s' % locals())

    if not approved_by_author or \
            missing_leader_approvals > 0 or \
            missing_peer_approvals > 0 or \
            (requires_unanimity and not is_unanimous) or \
            len(change_requests) > 0:
        raise messages.ApprovalRequired(
            pr=job.pull_request,
            required_leader_approvals=required_leader_approvals,
            leaders=list(leaders),
            required_peer_approvals=required_peer_approvals,
            requires_unanimity=requires_unanimity,
            requires_author_approval=job.settings.need_author_approval,
            active_options=job.active_options,
            change_requesters=list(change_requests)
        )


def check_build_status(job, wbranches):
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

    def status(branch):
        return job.project_repo.get_build_status(
            branch.get_latest_commit(), key)

    statuses = {b.name: status(b) for b in wbranches}
    worst = max(wbranches, key=lambda b: ordered_state[statuses[b.name]])
    worst_status = statuses[worst.name]
    if worst_status in ('FAILED', 'STOPPED'):
        raise messages.BuildFailed(
            active_options=job.active_options,
            branch=worst.name,
            build_url=job.project_repo.get_build_url(
                worst.get_latest_commit,
                key),
            commit_url=job.project_repo.get_commit_url(
                worst.get_latest_commit()),
        )
    elif worst_status == 'NOTSTARTED':
        raise messages.BuildNotStarted()
    elif worst_status == 'INPROGRESS':
        raise messages.BuildInProgress()
    assert worst_status == 'SUCCESSFUL'
