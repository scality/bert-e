#!/usr/bin/env python
# -*- coding: utf-8 -*-


class WallE_Exception(Exception):
    pass


class WallE_InternalException(Exception):
    # TODO send an email to releng
    pass


class CommentAlreadyExistsException(WallE_InternalException):
    pass


class AuthorApprovalRequiredException(WallE_Exception):
    def __init__(self, child_pull_requests):
        if len(child_pull_requests) == 0:
            msg = 'Waiting for author approval on this PR (manual port) or parent (auto port).'
        else:
            msg = 'The author of this pull request has not approved it.\n\n'
            msg += 'The author may :\n\n'
            msg += '* either approve this pull request and let me merge all versions mentionned in the Fix Version/s ticket automatically (auto port).\n'
            msg += '* or approve child pull requests individually if you want more control (manual port):\n'
            for pr in child_pull_requests:
                msg += '    * %s (pull request #%s)' % (data['destination']['branch']['name'], pr.id)

        return WallE_Exception.__init__(self, msg)


class PeerApprovalRequiredException(WallE_Exception):
    def __init__(self, child_pull_requests):
        msg = 'Waiting for all reviewers to approve this PR.'
        return WallE_Exception.__init__(self, msg)


class UnrecognizedBranchPatternException(WallE_Exception):
    pass


class VersionMismatchException(WallE_Exception):
    pass


class NotMyJobException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = "Sorry! It is not my job to merge `%s` into `%s`.\n\n" % (branch_to_be_merged, current_branch)
        msg += "You can do it by yourself! The button is in the top-right corner :arrow_heading_up:"
        return WallE_Exception.__init__(self, msg)


class NothingToDoException(WallE_InternalException):
    pass


class PrefixCannotBeMergedException(WallE_Exception):
    def __init__(self, branch_to_be_merged):
        msg = "Sorry buddy! I cannot merge the branch `%s` into `development/*` branches\n\n" % branch_to_be_merged
        msg += "The only patterns accepted are :\n"
        msg += "```"
        msg += "feature/RING-*\n"
        msg += "bugfix/RING-*\n"
        msg += "enhancement/RING-*\n"
        msg += "```"
        msg += "You should rename your branch and retry!"
        return WallE_Exception.__init__(self, msg)


class BranchDoesNotAcceptFeaturesException(WallE_Exception):
    def __init__(self, branch_to_be_merged):
        msg = "Sorry buddy! I cannot accept a `feature/*` branch in a maintenance branch\n\n"
        msg += "The only patterns accepted are :\n\n"
        msg += "```\n"
        msg += "bugfix/RING-*\n"
        msg += "enhancement/RING-*\n"
        msg += "```\n"
        msg += "You should rename your branch and retry!\n"
        return WallE_Exception.__init__(self, msg)


# TODO: remove the following exception
class ManualModeException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = "You have requested the manual mode."
        msg += "I've prepared the integration branch but you need to merge manually.\n"
        msg += "Next steps :\n"
        msg += '```\n'
        msg += '#!bash\n'
        msg += " $ git checkout %s\n" % current_branch
        msg += " $ git merge %s\n" % branch_to_be_merged
        msg += " $ # fix the conflicts if any.\n"
        msg += " $ git add <any modified file>\n"
        msg += " $ git commit\n"
        msg += " $ git push\n"
        msg += '```\n'
        msg += "After that, send your pull request id to release.engineering@scality.com so we start again\n\n"
        msg += "Note : This last (annoying) step will be automated in the next days"
        return WallE_Exception.__init__(self, msg)


class CheckoutFailedException(WallE_InternalException):
    pass


class PushFailedException(WallE_InternalException):
    pass


class BranchCreationFailedException(WallE_InternalException):
    pass


class MergeFailedException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = "Ouch:bangbang: I've encountered a conflict when I tried to merge `%s` into `%s`.\n\n" % (
            branch_to_be_merged, current_branch)
        msg += "Steps to resolve :\n"
        msg += '```\n'
        msg += '#!bash\n'
        msg += " $ git fetch\n"
        msg += " $ git checkout %s\n" % current_branch
        msg += " $ git merge origin/%s\n" % branch_to_be_merged
        msg += " $ # intense conflict fixing\n"
        msg += " $ git add <any modified file>\n"
        msg += " $ git commit\n"
        msg += " $ git push\n"
        msg += '```\n'
        msg += "After that, send your pull request id to release.engineering@scality.com so we start again\n\n"
        msg += "Note : This last (annoying) step will be automated in the next days"
        return WallE_Exception.__init__(self, msg)
