#!/usr/bin/env python
# -*- coding: utf-8 -*-

class WallE_Exception(Exception):
    pass


class AuthorApprovalRequiredException(WallE_Exception):
    def __init__(self, child_pull_requests):
        if len(child_pull_requests) == 0:
            msg = 'You must approve this pull request if you want me to merge it!'
        else:
            ids = 'pull request #' + ', pull request #'.join([str(pr.id) for pr in child_pull_requests])
            msg = 'Your approval on the pull request is missing.\n\n'
            msg += 'You may either :\n\n'
            msg += ' * Approve this pull request and let me merge all subsequent versions automagically.\n'
            msg += ' * Approve child pull requests individually [%s] if you want more control.\n\n' % ids

        return WallE_Exception.__init__(self, msg)


class PeerApprovalRequiredException(WallE_Exception):
    def __init__(self, child_pull_requests):
        if len(child_pull_requests) == 0:
            msg = 'A reviewer must approve this pull request before I can merge it!'
        else:
            ids = 'pull request #' + ', pull request #'.join([str(pr.id) for pr in child_pull_requests])
            msg = 'A peer approval on the pull request is missing.\n\n'
            msg += 'The reviewer may either :\n\n'
            msg += ' * Approve this pull request and let me merge all subsequent versions automagically\n'
            msg += ' * Approve child pull requests individually [%s] if you want more control\n' % ids

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


class NothingToDoException(WallE_Exception):
    def __init__(self, reason):
        msg = "Hey! Nothing to do here! %s.\n" % (reason)
        return WallE_Exception.__init__(self, msg)


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


class MergeFailedException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = "Ouch:bangbang: I've encountred a conflict when I tried to merge `%s` into `%s`.\n\n" % (
            branch_to_be_merged, current_branch)
        msg += "Steps to resolve :\n"
        msg += '```\n'
        msg += '#!bash\n'
        msg += " $ git fetch %s\n"
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
