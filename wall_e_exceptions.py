#!/usr/bin/env python
# -*- coding: utf-8 -*-

from template_loader import render


# base exceptions
class WallE_TemplateException(Exception):
    def __init__(self, **kwargs):
        msg = render(self.template, code=self.code, **kwargs)
        super(WallE_TemplateException, self).__init__(msg)


class WallE_InternalException(Exception):
    pass


class WallE_SilentException(Exception):
    pass


# template exceptions
class InitMessage(WallE_TemplateException):
    code = 10000
    template = 'init.md'


class HelpMessage(WallE_TemplateException):
    code = 10001
    template = 'help.md'


class CommandNotImplemented(WallE_TemplateException):
    code = 10002
    template = 'not_implemented.md'


class StatusReport(WallE_TemplateException):
    code = 10003
    template = 'status.md'


class BuildFailed(WallE_TemplateException):
    code = 10004
    template = 'build_failed.md'


class BuildInProgress(WallE_TemplateException):
    code = 10005
    template = 'build_in_progress.md'


class BuildNotStarted(WallE_TemplateException):
    code = 10006
    template = 'build_not_started.md'


class Conflict(WallE_TemplateException):
    code = 10007
    template = 'conflict.md'


class AuthorApprovalRequired(WallE_TemplateException):
    code = 10008
    template = 'need_approval.md'


class PeerApprovalRequired(WallE_TemplateException):
    code = 10009
    template = 'need_approval.md'


class MissingJiraIdMaintenance(WallE_TemplateException):
    code = 10010
    template = 'missing_jira_id_for_maintenance_branch.md'


class MismatchPrefixIssueType(WallE_TemplateException):
    code = 10011
    template = 'mismatch_prefix_issue_type.md'


class IncorrectFixVersion(WallE_TemplateException):
    code = 10012
    template = 'incorrect_fix_version.md'


class PrefixCannotBeMerged(WallE_TemplateException):
    code = 10013
    template = 'forbidden_branch.md'


class BranchDoesNotAcceptFeatures(WallE_TemplateException):
    code = 10014
    template = 'forbidden_branch_in_maintenance.md'


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


class ParentNotFound(WallE_InternalException):
    def __init__(self, pr_id):
        msg = ("The parent Pull Request from this pull request #%s"
               " couldn't be found." % pr_id)
        super(ParentNotFound, self).__init__(msg)


class JiraUnknownIssueType(WallE_InternalException):
    def __init__(self, issue_type):
        msg = ("Jira issue: unknown type %r" % issue_type)
        super(JiraUnknownIssueType, self).__init__(msg)


# silent exceptions
class CommentAlreadyExists(WallE_SilentException):
    pass


class NotMyJob(WallE_SilentException):
    pass


class NothingToDo(WallE_SilentException):
    pass
