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
"""Implementation of various checks performed on Jira issues.

This module is kept separate from the rest of GWF implementation because it is
likely to become a plugin in the future (when other ticket systems are
supported).

"""
import logging
import re

from jira.exceptions import JIRAError

from bert_e import exceptions
from bert_e.lib import jira as jira_api
from ..pr_utils import find_comment, notify_user
from .utils import bypass_jira_check


LOG = logging.getLogger(__name__)


def jira_checks(job):
    """Performs consistency checks against associated Jira issue."""
    if bypass_jira_check(job):
        return

    if job.git.src_branch.prefix in job.settings.bypass_prefixes:
        LOG.debug("Bypassing JIRA checks due to branch prefix '%s'",
                  job.git.src_branch.prefix)
        return

    if not all([job.settings.jira_keys,
                job.settings.jira_email,
                job.settings.jira_account_url]):
        return

    if not check_issue_reference(job):
        return

    issue = get_jira_issue(job)
    check_project(job, issue)
    check_issue_type(job, issue)

    if not job.settings.disable_version_checks:
        check_fix_versions(job, issue)
        _notify_pending_hotfix_if_needed(job, issue)


def get_jira_issue(job):
    """Return the jira issue associated with a pull request.

    Raises:
        JiraIssueNotFound: if the issue doesn't exist.

    """
    try:
        return jira_api.JiraIssue(
            account_url=job.settings.jira_account_url,
            issue_id=job.git.src_branch.jira_issue_key,
            email=job.settings.jira_email,
            token=job.settings.jira_token
        )
    except JIRAError as err:
        if err.status_code == 404:
            raise exceptions.JiraIssueNotFound(
                issue=job.git.src_branch.jira_issue_key,
                active_options=job.active_options
            ) from err
        raise


def check_issue_reference(job) -> bool:
    """Check that the name of the pull request's source branch references
    a jira through an issue id.

    Returns:
        True if the source branch references a jira issue. False otherwise.

    Raises:
        MissingJiraId: if there is no issue id and any of the destination
                       branches doesn't allow ticketless pull requests.

    """

    src_branch = job.git.src_branch
    if not src_branch.jira_issue_key:
        for dst_branch in job.git.cascade.dst_branches:
            if not dst_branch.allow_ticketless_pr:
                raise exceptions.MissingJiraId(
                    source_branch=src_branch.name, dest_branch=dst_branch.name,
                    active_options=job.active_options
                )
        return False
    return True


def check_project(job, issue):
    """Check that the jira project referenced by the pull request is one
    we authorize.

    Raises:
        IncorrectJiraProject: if the project is not handled by this instance
                              of BertE.

    """
    if job.git.src_branch.jira_project not in job.settings.jira_keys:
        raise exceptions.IncorrectJiraProject(
            issue=issue, expected_project=', '.join(job.settings.jira_keys),
            active_options=job.active_options
        )


def check_issue_type(job, issue):
    """Check if the Jira issue is of a supported type.

    Raises:
        IssueTypeNotSupported if the issue is not of a type explicitely
        supported in the configuration.

    """
    issuetype = issue.fields.issuetype.name
    prefixes = job.settings.prefixes
    if not prefixes:
        return

    if issuetype not in prefixes:
        raise exceptions.IssueTypeNotSupported(
            issue=issue, pairs=prefixes, active_options=job.active_options
        )


def check_fix_versions(job, issue):
    """Check that the fixVersions field of the Jira issue correctly documents
    the versions this pull request is actually targetting.

    Raises:
        IncorrectFixVersion: if versions are inconsistent.

    """
    issue_versions = set(version.name for version in issue.fields.fixVersions)
    expected_versions = set(job.git.cascade.target_versions)

    # Ignore suffixed versions such as "5.1.9_hf7" in that check
    # Do not ignore X.Y.Z.0 version
    vfilter = re.compile(r'^\d+\.\d+\.\d+(\.0|)$')
    checked_versions = set(v for v in issue_versions if vfilter.match(v))

    # If the job is targetting a hotfix branch, feed hf_target with the version
    hf_target = None
    if len(expected_versions) == 1:
        target_version = list(expected_versions)[0]
        hf_filter = re.compile(r'^\d+\.\d+\.\d+\.\d+$')
        if hf_filter.match(target_version):
            hf_target = target_version

    if hf_target:
        # Hotfix PR: the ticket must carry the exact 4-digit target version
        # (e.g. "10.0.0.0" pre-GA, "10.0.0.1" post-GA first hotfix, …).
        # 3-digit aliases are no longer accepted — a 4-digit entry makes it
        # unambiguous whether the branch is still pre-GA or an actual hotfix.
        if hf_target not in issue_versions:
            raise exceptions.IncorrectFixVersion(
                issue=issue,
                issue_versions=sorted(issue_versions),
                expect_versions=sorted(expected_versions),
                active_options=job.active_options
            )
    else:
        # Development-branch PR: versions that belong to a phantom hotfix
        # branch (pre-GA hotfix/X.Y.Z stored outside the cascade) will be
        # consumed by the separate cherry-pick PR to that hotfix branch.
        # Strip them so they don't cause a spurious mismatch here.
        checked_versions -= job.git.cascade.phantom_hotfix_versions
        if checked_versions != expected_versions:
            raise exceptions.IncorrectFixVersion(
                issue=issue,
                issue_versions=sorted(issue_versions),
                expect_versions=sorted(expected_versions),
                active_options=job.active_options
            )


_PENDING_HOTFIX_TITLE = '# Pending hotfix branch'


def _notify_pending_hotfix_if_needed(job, issue):
    """Post a one-time reminder when the ticket carries a pre-GA hotfix
    fix version (X.Y.Z.0) so the developer knows to open a cherry-pick PR
    to the corresponding hotfix branch.

    This is an informational message: it is posted at most once per PR
    and never blocks the flow.

    The standard dont_repeat_if_in_history dedup uses the full rendered
    message as the match key, which includes the active_options footer.
    Because active_options can change between runs (e.g. when
    create_integration_branches is added), the footer-sensitive match would
    miss a comment posted in an earlier run and post again. We guard with
    an explicit title-prefix check first, which is stable across runs.
    """
    phantom_versions = job.git.cascade.phantom_hotfix_versions
    if not phantom_versions:
        return
    issue_versions = {v.name for v in issue.fields.fixVersions}
    matching = sorted(phantom_versions & issue_versions)
    if not matching:
        return
    # Stable dedup: any previous comment with this title means skip.
    if find_comment(job.pull_request, job.settings.robot,
                    startswith=_PENDING_HOTFIX_TITLE):
        return
    reminder = exceptions.PendingHotfixVersionReminder(
        issue=issue,
        hotfix_versions=matching,
        active_options=job.active_options,
    )
    notify_user(job.settings, job.pull_request, reminder)
