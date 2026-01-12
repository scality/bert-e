# Copyright 2016-2026 Scality
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
"""Babysit feature - automatic retry of failed GitHub Actions builds.

This module provides the babysit functionality that automatically retries
failed GitHub Actions builds when the /babysit option is enabled on a
pull request. The feature:

1. Monitors build failures on any branch (integration branches w/*, queue
   branches, etc.)
2. Automatically triggers GitHub's "Re-run failed jobs" for failed workflow
   runs
3. Tracks retry count PER WORKFLOW by parsing Bert-E's BabysitRetry comments
   since the last /babysit command from the user
4. After max_babysit_retries (configurable, default 5) for a workflow, that
   workflow is considered exhausted. When ALL failed workflows are exhausted,
   posts a BabysitExhausted notification
5. Users can comment /babysit again to reset all retry counters and get
   additional retries
6. If new commits are pushed, babysit is cancelled and must be re-invoked

"""
import logging
import re
from collections import defaultdict

from bert_e import exceptions as messages


LOG = logging.getLogger(__name__)

# Marker text used to identify BabysitRetry comments from Bert-E
BABYSIT_RETRY_MARKER = "Babysit: Retrying build"

# Regex to extract commit SHA from BabysitRetry comments
# Matches: (commit `abc1234`) where abc1234 is 7+ hex chars
COMMIT_SHA_PATTERN = re.compile(r'\(commit `([a-f0-9]{7,40})`\)')

# Regex to extract workflow names from the retry table
# Matches: | `workflow_name` | X/Y |
WORKFLOW_RETRY_PATTERN = re.compile(r'\| `([^`]+)` \| (\d+)/(\d+) \|')


def count_babysit_retries_per_workflow(pull_request, robot_name, branch_name,
                                        current_commit):
    """Count how many babysit retries have been done for each workflow.

    This parses BabysitRetry comments posted by Bert-E for the specific branch
    since the last /babysit command, and extracts retry counts per workflow.

    Also detects if babysit is "stale" - i.e., retries were done for a
    different commit than the current one.

    Args:
        pull_request: The pull request to check comments on.
        robot_name: The robot's username (e.g., "bert-e").
        branch_name: The branch name to count retries for.
        current_commit: The current commit SHA on the branch.

    Returns:
        tuple: (workflow_retries, is_stale, previous_commit)
            - workflow_retries: dict mapping workflow name to retry count
            - is_stale: True if retries were for a different commit.
            - previous_commit: The commit SHA from previous retries (if stale),
                               or None.

    """
    workflow_retries = defaultdict(int)
    previous_commit = None
    is_stale = False

    # Pattern to find /babysit command from users
    babysit_cmd_pattern = re.compile(
        r'@' + re.escape(robot_name) + r'\s+babysit\b',
        re.IGNORECASE
    )

    for comment in pull_request.comments:
        author = comment.author
        text = comment.text

        if author == robot_name:
            # Check if this is a BabysitRetry comment for our branch
            if (BABYSIT_RETRY_MARKER in text and
                    f"`{branch_name}`" in text):

                # Extract commit SHA from the comment
                sha_match = COMMIT_SHA_PATTERN.search(text)
                if sha_match:
                    comment_commit = sha_match.group(1)
                    # Check if this retry was for a different commit
                    if not current_commit.startswith(comment_commit):
                        is_stale = True
                        previous_commit = comment_commit

                # Extract workflow retry counts from the table
                for wf_match in WORKFLOW_RETRY_PATTERN.finditer(text):
                    workflow_name = wf_match.group(1)
                    # The retry count in the message is the current retry number
                    # We just need to track that this workflow was retried
                    workflow_retries[workflow_name] += 1
        else:
            # Check if user sent /babysit command - this resets all counts
            if babysit_cmd_pattern.search(text):
                workflow_retries = defaultdict(int)
                is_stale = False
                previous_commit = None

    return dict(workflow_retries), is_stale, previous_commit


def handle_babysit_retry(job, failed_branch, build_key, pull_request=None):
    """Handle babysit retry logic for failed builds.

    This function is called when a build fails and the babysit option is
    enabled. It will automatically retry the failed GitHub Actions jobs
    up to max_babysit_retries times PER WORKFLOW.

    The retry count is tracked per workflow by parsing Bert-E's BabysitRetry
    comments since the last /babysit command. This allows users to re-invoke
    /babysit to get additional retries after exhaustion.

    If new commits are pushed after babysit was invoked, babysit is
    cancelled and the user must re-invoke it.

    Args:
        job: The current job.
        failed_branch: The branch with the failed build (integration branch,
                       queue branch, or any branch).
        build_key: The build key being checked (must be 'github_actions').
        pull_request: Optional pull request to check for comments. If not
                      provided, uses job.pull_request.

    Returns:
        True if babysit handled the failure (always raises an exception).
        False if babysit is not applicable.

    Raises:
        BabysitRetry: if retrying the failed jobs.
        BabysitExhausted: if max retries reached for all failed workflows.
        BabysitCancelled: if new commits were pushed since babysit was invoked.

    """
    # Use the provided pull_request or fall back to job's pull_request
    pr = pull_request or getattr(job, 'pull_request', None)
    if pr is None:
        LOG.debug("Babysit: no pull request available")
        return False

    # Check if babysit is enabled
    if not job.settings.babysit:
        return False

    # Babysit only works for GitHub with github_actions build key
    if job.settings.repository_host != 'github':
        LOG.debug("Babysit: skipping, not GitHub host")
        return False

    if build_key != 'github_actions':
        LOG.debug("Babysit: skipping, build_key is not github_actions")
        return False

    branch_name = failed_branch.name
    commit_sha = failed_branch.get_latest_commit()
    max_retries = job.settings.max_babysit_retries

    LOG.info("Babysit: checking failed build on branch %s (commit %s)",
             branch_name, commit_sha[:7])

    # Count existing retries per workflow and check for stale babysit
    workflow_retries, is_stale, previous_commit = \
        count_babysit_retries_per_workflow(
            pr, job.settings.robot, branch_name, commit_sha
        )

    LOG.info("Babysit: branch=%s, workflow_retries=%s, is_stale=%s",
             branch_name, workflow_retries, is_stale)

    build_url = job.project_repo.get_build_url(commit_sha, build_key)

    # Check if babysit is stale (new commits pushed since babysit was invoked)
    if is_stale and previous_commit:
        LOG.info("Babysit: cancelled for %s due to new commits "
                 "(was: %s, now: %s)",
                 branch_name, previous_commit, commit_sha[:7])
        raise messages.BabysitCancelled(
            active_options=job.active_options,
            branch=failed_branch,
            previous_commit=previous_commit,
            current_commit=commit_sha,
            robot=job.settings.robot,
        )

    # Get the workflow runs for the failed commit
    from bert_e.git_host.github import AggregatedWorkflowRuns

    try:
        workflow_runs = AggregatedWorkflowRuns.get(
            client=job.project_repo.client,
            owner=job.settings.repository_owner,
            repo=job.settings.repository_slug,
            params={'head_sha': commit_sha}
        )
    except Exception as err:
        LOG.warning("Babysit: failed to get workflow runs for %s: %s",
                    branch_name, err)
        return False

    # Get failed runs
    failed_runs = workflow_runs.get_failed_runs()
    if not failed_runs:
        LOG.debug("Babysit: no failed workflow runs found for %s", branch_name)
        return False

    # Categorize workflows: which can be retried, which are exhausted
    workflows_to_retry = []
    exhausted_workflows = []

    for run in failed_runs:
        workflow_name = run.get('name', f"workflow_{run['id']}")
        current_count = workflow_retries.get(workflow_name, 0)

        if current_count >= max_retries:
            LOG.info("Babysit: workflow '%s' exhausted (%d/%d)",
                     workflow_name, current_count, max_retries)
            exhausted_workflows.append(workflow_name)
        else:
            workflows_to_retry.append({
                'id': run['id'],
                'name': workflow_name,
                'retry_count': current_count + 1,  # This will be the new count
            })

    # If all failed workflows are exhausted, raise BabysitExhausted
    if not workflows_to_retry and exhausted_workflows:
        LOG.info("Babysit: all workflows exhausted for %s: %s",
                 branch_name, exhausted_workflows)
        raise messages.BabysitExhausted(
            active_options=job.active_options,
            branch=failed_branch,
            build_url=build_url,
            max_retries=max_retries,
            robot=job.settings.robot,
            exhausted_workflows=exhausted_workflows,
        )

    # If no workflows to retry (but also none exhausted), something is off
    if not workflows_to_retry:
        LOG.warning("Babysit: no workflows to retry and none exhausted for %s",
                    branch_name)
        return False

    # Trigger re-run of each workflow that hasn't exhausted retries
    rerun_triggered = False
    for wf in workflows_to_retry:
        try:
            LOG.info("Babysit: re-running failed jobs for workflow '%s' "
                     "(id=%d) on %s, retry %d/%d",
                     wf['name'], wf['id'], branch_name,
                     wf['retry_count'], max_retries)
            job.project_repo.rerun_failed_workflow_jobs(wf['id'])
            rerun_triggered = True
        except Exception as err:
            LOG.warning("Babysit: failed to rerun workflow %d (%s) on %s: %s",
                        wf['id'], wf['name'], branch_name, err)

    if not rerun_triggered:
        LOG.warning("Babysit: could not trigger any reruns for %s", branch_name)
        return False

    # Raise BabysitRetry with per-workflow information
    raise messages.BabysitRetry(
        active_options=job.active_options,
        branch=failed_branch,
        build_url=build_url,
        commit_sha=commit_sha,
        workflows=workflows_to_retry,
        max_retries=max_retries,
    )
