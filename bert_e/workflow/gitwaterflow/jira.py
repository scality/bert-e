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


LOG = logging.getLogger(__name__)


def jira_checks(job):
    """Performs consistency checks against associated Jira issue."""
    if job.settings.bypass_jira_check:
        return

    if job.git.src_branch.prefix in job.settings.bypass_prefixes:
        LOG.debug("Bypassing JIRA checks due to branch prefix '%s'",
                  job.git.src_branch.prefix)
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

    if not job.settings.disable_version_checks:
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
    vfilter = re.compile('^\d+\.\d+\.\d+$')
    checked_versions = set(v for v in issue_versions if vfilter.match(v))

    if checked_versions != expected_versions:
        raise exceptions.IncorrectFixVersion(
            issue=issue,
            issue_versions=sorted(issue_versions),
            expect_versions=sorted(expected_versions),
            active_options=job.active_options
        )
