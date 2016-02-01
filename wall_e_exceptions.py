#!/usr/bin/env python
# -*- coding: utf-8 -*-

from template_loader import render


# base exceptions
class WallE_TemplateException(Exception):
    code = 0
    template = None
    # whether to re-publish if the message is already in the history
    dont_repeat_if_in_history = 10

    def __init__(self, **kwargs):
        assert self.code != 0
        assert self.template
        self.msg = render(self.template, code=self.code, **kwargs)
        super(WallE_TemplateException, self).__init__(self.msg)


class WallE_InternalException(Exception):
    pass


class WallE_SilentException(Exception):
    pass


# template exceptions
class InitMessage(WallE_TemplateException):
    code = 100
    template = 'init.md'


class HelpMessage(WallE_TemplateException):
    code = 101
    template = 'help.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class CommandNotImplemented(WallE_TemplateException):
    code = 102
    template = 'not_implemented.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class StatusReport(WallE_TemplateException):
    code = 103
    template = 'status.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class BuildFailed(WallE_TemplateException):
    code = 104
    template = 'build_failed.md'


class BuildInProgress(WallE_TemplateException):
    code = 105
    template = 'build_in_progress.md'


class BuildNotStarted(WallE_TemplateException):
    code = 106
    template = 'build_not_started.md'


class Conflict(WallE_TemplateException):
    code = 107
    template = 'conflict.md'


class AuthorApprovalRequired(WallE_TemplateException):
    code = 108
    template = 'need_approval.md'


class PeerApprovalRequired(WallE_TemplateException):
    code = 109
    template = 'need_approval.md'


class MissingJiraIdMaintenance(WallE_TemplateException):
    code = 110
    template = 'missing_jira_id_for_maintenance_branch.md'


class MismatchPrefixIssueType(WallE_TemplateException):
    code = 111
    template = 'mismatch_prefix_issue_type.md'


class IncorrectFixVersion(WallE_TemplateException):
    code = 112
    template = 'incorrect_fix_version.md'


class IncorrectBranchName(WallE_TemplateException):
    code = 113
    template = 'forbidden_branch.md'


class BranchDoesNotAcceptFeatures(WallE_TemplateException):
    code = 114
    template = 'forbidden_branch_in_maintenance.md'


class BranchHistoryMismatch(WallE_TemplateException):
    code = 115
    template = 'history_mismatch.md'


class JiraIssueNotFound(WallE_TemplateException):
    code = 116
    template = 'jira_issue_not_found.md'


class ParentJiraIssueNotFound(JiraIssueNotFound):
    code = 117
    template = 'parent_jira_issue_not_found.md'


class SuccessMessage(WallE_TemplateException):
    code = 118
    template = 'successfull_merge.md'


class TesterApprovalRequired(WallE_TemplateException):
    code = 119
    template = 'need_approval.md'


# internal exceptions
class UnableToSendEmail(WallE_InternalException):
    pass


class ImproperEmailFormat(WallE_InternalException):
    pass


class BranchNameInvalid(WallE_InternalException):
    def __init__(self, name):
        self.branch = name
        msg = 'Invalid name: %r' % name
        super(BranchNameInvalid, self).__init__(msg)


class ParentPullRequestNotFound(WallE_InternalException):
    def __init__(self, pr_id):
        msg = ("The parent Pull Request from this pull request #%s"
               " couldn't be found." % pr_id)
        super(ParentPullRequestNotFound, self).__init__(msg)


class JiraUnknownIssueType(WallE_InternalException):
    def __init__(self, issue_type):
        msg = ("Jira issue: unknown type %r" % issue_type)
        super(JiraUnknownIssueType, self).__init__(msg)


class MalformedGitRepo(WallE_InternalException):
    def __init__(self, upstream_branch, downstream_branch):
        msg = ("The git repository appears to be in a bad shape. "
               "Branch `%s` is not included in branch `%s`." % (
               upstream_branch, downstream_branch))
        super(MalformedGitRepo, self).__init__(msg)


# silent exceptions
class CommentAlreadyExists(WallE_SilentException):
    pass


class NotMyJob(WallE_SilentException):
    pass


class NothingToDo(WallE_SilentException):
    pass
