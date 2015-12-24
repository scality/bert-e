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
            msg = ('Waiting for author approval on this PR (manual port)'
                   ' or parent (auto port).')
        else:
            msg = ('The author of this pull request has not approved it.\n\n'
                   'The author may :\n\n'
                   '* either approve this pull request and let me merge'
                   'all versions mentionned in the Fix Version/s ticket '
                   'automatically (auto port).\n'
                   '* or approve child pull requests individually '
                   'if you want more control (manual port):\n')
            for pr in child_pull_requests:
                msg += ('    * %s (pull request #%s)'
                        % (pr['destination']['branch']['name'], pr['id']))

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
        msg = ("Sorry! It is not my job to merge `%s` into `%s`.\n\n"
               "You can do it by yourself! The button is in the top-right "
               "corner :arrow_heading_up:"
               % (branch_to_be_merged, current_branch))
        return WallE_Exception.__init__(self, msg)


class NothingToDoException(WallE_InternalException):
    pass


class PrefixCannotBeMergedException(WallE_Exception):
    def __init__(self, branch_to_be_merged):
        msg = ("Sorry buddy! I cannot merge the branch `%s` into "
               "`development/*` branches\n\n"
               "The only patterns accepted are :\n"
               "```"
               "feature/RING-*\n"
               "bugfix/RING-*\n"
               "enhancement/RING-*\n"
               "```"
               "You should rename your branch and retry!"
               % branch_to_be_merged)
        return WallE_Exception.__init__(self, msg)


class BranchDoesNotAcceptFeaturesException(WallE_Exception):
    def __init__(self, branch_to_be_merged):
        msg = ("Sorry buddy! I cannot accept a `feature/*` branch "
               "in a maintenance branch\n\n"
               "The only patterns accepted are :\n\n"
               "```\n"
               "bugfix/RING-*\n"
               "enhancement/RING-*\n"
               "```\n"
               "You should rename your branch and retry!\n")
        return WallE_Exception.__init__(self, msg)


# TODO: remove the following exception
class ManualModeException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = ("You have requested the manual mode."
               "I've prepared the integration branch but "
               "you need to merge manually.\n"
               "Next steps :\n"
               '```\n'
               '#!bash\n'
               " $ git checkout %s\n"
               " $ git merge %s\n"
               " $ # fix the conflicts if any.\n"
               " $ git add <any modified file>\n"
               " $ git commit\n"
               " $ git push\n"
               '```\n'
               "After that, send your pull request id to "
               "release.engineering@scality.com so we start again\n\n"
               "Note : This last (annoying) step "
               "will be automated in the next days"
               % (current_branch, branch_to_be_merged))
        return WallE_Exception.__init__(self, msg)


class ConflictException(WallE_Exception):
    def __init__(self, current_branch, branch_to_be_merged):
        msg = ("Ouch:bangbang: I've encountered a conflict when I tried "
               "to merge `%s` into `%s`.\n\n"
               "Steps to resolve :\n"
               '```\n'
               '#!bash\n'
               " $ git fetch\n"
               " $ git checkout %s\n"
               " $ git merge origin/%s\n"
               " $ # intense conflict fixing\n"
               " $ git add <any modified file>\n"
               " $ git commit\n"
               " $ git push\n"
               '```\n'
               "After that, send your pull request id to "
               "release.engineering@scality.com so we start again\n\n"
               "Note : This last (annoying) step will be automated "
               "in the next days"
               % (branch_to_be_merged, current_branch,
                  current_branch, branch_to_be_merged))
        return WallE_Exception.__init__(self, msg)
