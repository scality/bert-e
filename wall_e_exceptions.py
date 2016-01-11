#!/usr/bin/env python
# -*- coding: utf-8 -*-

from template_loader import render


# base exceptions
class WallE_TemplateException(Exception):
    def __init__(self, **kwargs):
        msg = render(self.template, **kwargs)
        Exception.__init__(self, msg)


class WallE_InternalException(Exception):
    pass


class WallE_SilentException(Exception):
    pass


# derived exceptions
class UnableToSendEmail(WallE_InternalException):
    pass


class ImproperEmailFormat(WallE_InternalException):
    pass


class CommentAlreadyExists(WallE_SilentException):
    pass


class AuthorApprovalRequired(WallE_TemplateException):
    template = 'need_approval.md'


class PeerApprovalRequired(WallE_TemplateException):
    template = 'need_approval.md'


class MissingJiraIdMaintenance(WallE_TemplateException):
    template = 'missing_jira_id_for_maintenance_branch.md'


class MismatchPrefixIssueType(WallE_TemplateException):
    template = 'mismatch_prefix_issue_type.md'


class IncorrectFixVersion(WallE_TemplateException):
    template = 'incorrect_fix_version.md'


class HelpMessage(WallE_TemplateException):
    template = 'help.md'


class StatusReport(WallE_TemplateException):
    template = 'status.md'


class CommandNotImplemented(WallE_TemplateException):
    template = 'not_implemented.md'


class InitMessage(WallE_TemplateException):
    template = 'init.md'


class NotMyJob(WallE_SilentException):
    pass


class NothingToDo(WallE_SilentException):
    pass


class BranchNameInvalid(WallE_InternalException):
    def __init__(self, name):
        self.branch = name
        WallE_InternalException.__init__(self, 'Invalid name: %r' % name)


class PrefixCannotBeMerged(WallE_TemplateException):
    template = 'forbidden_branch.md'


class BranchDoesNotAcceptFeatures(WallE_TemplateException):
    template = 'forbidden_branch_in_maintenance.md'


class Conflict(WallE_TemplateException):
    template = 'conflict.md'


class BuildFailed(WallE_TemplateException):
    template = 'build_failed.md'


class BuildInProgress(WallE_SilentException):
    pass


class BuildNotStarted(WallE_SilentException):
    pass


class ParentNotFound(WallE_InternalException):
    def __init__(self, pr_id):
        msg = ("The parent Pull Request from this pull request #%s"
               " couldn't be found." % pr_id)
        WallE_InternalException.__init__(self, msg)
