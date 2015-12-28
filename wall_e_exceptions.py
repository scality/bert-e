#!/usr/bin/env python
# -*- coding: utf-8 -*-

from template_loader import render


class WallE_Exception(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)


class WallE_TemplateException(Exception):
    def __init__(self, **kwargs):
        msg = render(self.template, **kwargs)
        Exception.__init__(self, msg)


class WallE_InternalException(Exception):
    # TODO send an email to releng
    pass


class CommentAlreadyExistsException(WallE_InternalException):
    pass


class AuthorApprovalRequiredException(WallE_TemplateException):
    template = 'need_approval.md'


class PeerApprovalRequiredException(WallE_TemplateException):
    template = 'need_approval.md'


class UnrecognizedBranchPatternException(WallE_Exception):
    pass


class NotMyJobException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = ("Not my job to merge `%s` into `%s`."
               % (branch_to_be_merged, current_branch))
        WallE_Exception.__init__(self, msg)


class NothingToDoException(WallE_InternalException):
    pass


class BranchNameInvalidException(WallE_Exception):
    def __init__(self, name):
        self.branch = name
        WallE_Exception.__init__(self, 'Invalid name: %r' % name)


class PrefixCannotBeMergedException(WallE_TemplateException):
    template = 'forbidden_branch.md'


class BranchDoesNotAcceptFeaturesException(WallE_TemplateException):
    template = 'forbidden_branch_in_maintenance.md'


class ConflictException(WallE_TemplateException):
    template = 'conflict.md'
