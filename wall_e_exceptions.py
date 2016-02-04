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
        assert self.dont_repeat_if_in_history >= 0
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


class SuccessMessage(WallE_TemplateException):
    code = 102
    template = 'successful_merge.md'


class CommandNotImplemented(WallE_TemplateException):
    code = 103
    template = 'not_implemented.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class StatusReport(WallE_TemplateException):
    code = 104
    template = 'status.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class IncorrectSourceBranchName(WallE_TemplateException):
    code = 105
    template = 'incorrect_source_branch_name.md'


class IncompatibleSourceBranchPrefix(WallE_TemplateException):
    code = 106
    template = 'incompatible_source_branch_prefix.md'


class MissingJiraId(WallE_TemplateException):
    code = 107
    template = 'missing_jira_id.md'


class JiraIssueNotFound(WallE_TemplateException):
    code = 108
    template = 'jira_issue_not_found.md'


class SubtaskIssueNotSupported(WallE_TemplateException):
    code = 109
    template = 'subtask_issue_not_supported.md'


class IncorrectJiraProject(WallE_TemplateException):
    code = 110
    template = 'incorrect_jira_project.md'


class MismatchPrefixIssueType(WallE_TemplateException):
    code = 111
    template = 'mismatch_prefix_issue_type.md'


class IncorrectFixVersion(WallE_TemplateException):
    code = 112
    template = 'incorrect_fix_version.md'


class BranchHistoryMismatch(WallE_TemplateException):
    code = 113
    template = 'history_mismatch.md'


class Conflict(WallE_TemplateException):
    code = 114
    template = 'conflict.md'


class AuthorApprovalRequired(WallE_TemplateException):
    code = 115
    template = 'need_approval.md'


class PeerApprovalRequired(WallE_TemplateException):
    code = 116
    template = 'need_approval.md'


class TesterApprovalRequired(WallE_TemplateException):
    code = 117
    template = 'need_approval.md'


class BuildFailed(WallE_TemplateException):
    code = 118
    template = 'build_failed.md'


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


class DevBranchesNotSelfContained(WallE_InternalException):
    def __init__(self, upstream_branch, downstream_branch):
        msg = ("The git repository appears to be in a bad shape. "
               "Branch `%s` is not included in branch `%s`." % (
                   upstream_branch, downstream_branch))
        super(DevBranchesNotSelfContained, self).__init__(msg)


class DevBranchDoesNotExist(WallE_InternalException):
    def __init__(self, branch):
        msg = ("The git repository appears to be in a bad shape. "
               "Branch `%s` does not exist." % branch)
        super(DevBranchDoesNotExist, self).__init__(msg)


# silent exceptions
class CommentAlreadyExists(WallE_SilentException):
    pass


class NotMyJob(WallE_SilentException):
    pass


class NothingToDo(WallE_SilentException):
    pass


class BuildInProgress(WallE_SilentException):
    pass


class BuildNotStarted(WallE_SilentException):
    pass
