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
"""Implementation of various checks performed on Jira issues.

This module is kept separate from the rest of GWF implementation because it is
likely to become a plugin in the future (when other ticket systems are
supported).

"""

from jira.exceptions import JIRAError

from bert_e import exceptions
from bert_e.api import jira as jira_api

from .commands import get_active_options


def jira_checks(job):
    """Performs consistency checks against associated Jira issue."""
    if job.settings.bypass_jira_check:
        return

    if not all([job.settings.jira_keys,
                job.settings.jira_username,
                job.settings.jira_account_url]):
        return

    if not check_issue_reference(job):
        return

    issue = get_jira_issue(job)
    check_project(job, issue)
    check_issue_type(job, issue)
    check_fix_versions(job, issue)


def get_jira_issue(job):
    """Return the jira issue associated with a pull request.

    Raises:
        JiraIssueNotFound: if the issue doesn't exist.

    """
    try:
        return jira_api.JiraIssue(
            account_url=job.settings.jira_account_url,
            issue_id=job.git.src_branch.jira_issue_key,
            login=job.settings.jira_username,
            passwd=job.settings.jira_password
        )
    except JIRAError as err:
        if err.status_code == 404:
            raise exceptions.JiraIssueNotFound(
                issue=job.issue_id, active_options=get_active_options(job)
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
                    active_options=get_active_options(job)
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
            active_options=get_active_options(job)
        )


def check_issue_type(job, issue):
    """Check if the Jira issue is of a supported type.

    Raises:
        SubtaskIssueNotSupported: if the issue is a subtask.

    """
    issuetype = issue.fields.issuetype.name
    prefixes = job.settings.get('prefixes')

    if issuetype == 'Sub-task':
        raise exceptions.SubtaskIssueNotSupported(
            issue=issue, pairs=prefixes, active_options=get_active_options(job)
        )


def check_fix_versions(job, issue):
    """Check that the fixVersions field of the Jira issue correctly documents
    the versions this pull request is actually targetting.

    Raises:
        IncorrectFixVersion: if versions are inconsistent.

    """
    issue_versions = set(version.name for version in issue.fields.fixVersions)
    expected_versions = set(job.git.cascade.target_versions)

    if issue_versions != expected_versions:
        raise exceptions.IncorrectFixVersion(
            issue=issue, issue_versions=issue_versions,
            expect_versions=expected_versions,
            active_options=get_active_options(job)
        )