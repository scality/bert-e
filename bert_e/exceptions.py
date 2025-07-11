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

from typing import Literal
from bert_e.lib.template_loader import render

# When dont_repeat_if_in_history is None, Bert-E will look for the message
# in the whole list of comments.
NEVER_REPEAT = None


class BertE_Exception(Exception):
    code = -1
    status: Literal[None, "in_progress", "queued", "success", "failure"] = None


# base exceptions
class TemplateException(BertE_Exception):
    code = -2
    template = None
    # whether to re-publish if the message is already in the history
    dont_repeat_if_in_history = -1

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        assert 'active_options' in kwargs
        assert self.code != 0
        assert self.template
        norepeat = self.dont_repeat_if_in_history
        assert norepeat is None or norepeat >= -1
        self.msg = render(self.template, code=self.code, **kwargs)
        super(TemplateException, self).__init__(self.msg)

    @property
    def title(self) -> str:
        # Return the exception class name as the title
        return self.__class__.__name__


class InternalException(BertE_Exception):
    code = 1


class SilentException(BertE_Exception):
    code = 2


# template for informative exceptions
class InformationException(TemplateException):
    dont_repeat_if_in_history = NEVER_REPEAT


# template exceptions
class InitMessage(InformationException):
    code = 100
    template = 'init.md'


class HelpMessage(TemplateException):
    code = 101
    template = 'help.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class SuccessMessage(TemplateException):
    code = 102
    template = 'successful_merge.md'
    status = "success"


class CommandNotImplemented(TemplateException):
    code = 103
    template = 'not_implemented.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class StatusReport(TemplateException):
    code = 104
    template = 'status.md'
    dont_repeat_if_in_history = 0  # allow repeating if requested by user


class IncompatibleSourceBranchPrefix(TemplateException):
    code = 106
    template = 'incompatible_source_branch_prefix.md'
    status = "failure"


class MissingJiraId(TemplateException):
    code = 107
    template = 'missing_jira_id.md'
    status = "failure"


class JiraIssueNotFound(TemplateException):
    code = 108
    template = 'jira_issue_not_found.md'
    status = "failure"


class IssueTypeNotSupported(TemplateException):
    code = 109
    template = 'issue_type_not_supported.md'
    status = "failure"


class IncorrectJiraProject(TemplateException):
    code = 110
    template = 'incorrect_jira_project.md'
    status = "failure"


class MismatchPrefixIssueType(TemplateException):
    code = 111
    template = 'mismatch_prefix_issue_type.md'
    status = "failure"


class IncorrectFixVersion(TemplateException):
    code = 112
    template = 'incorrect_fix_version.md'
    status = "failure"


class BranchHistoryMismatch(TemplateException):
    code = 113
    template = 'history_mismatch.md'
    status = "failure"


class Conflict(TemplateException):
    code = 114
    template = 'conflict.md'
    status = "failure"


class ApprovalRequired(TemplateException):
    code = 115
    template = 'need_approval.md'
    status = "queued"


class BuildFailed(TemplateException):
    code = 118
    template = 'build_failed.md'
    status = "failure"


class AfterPullRequest(TemplateException):
    code = 120
    template = 'after_pull_request.md'
    status = "queued"


class IntegrationDataCreated(InformationException):
    code = 121
    template = 'integration_data_created.md'


class UnknownCommand(TemplateException):
    code = 122
    template = 'unknown_command.md'
    status = "failure"


class NotEnoughCredentials(TemplateException):
    code = 123
    template = "not_enough_credentials.md"
    status = "failure"


class QueueConflict(TemplateException):
    code = 124
    template = "queue_conflict.md"
    status = "failure"


class Queued(TemplateException):
    code = 125
    template = 'queued.md'
    status = "in_progress"

    def __init__(self, branches, ignored, issue, author, active_options):
        """Save args for later use by tests."""
        self.branches = branches
        self.ignored = ignored
        self.issue = issue
        self.author = author
        self.active_options = active_options
        super(Queued, self).__init__(
            branches=branches,
            ignored=ignored,
            issue=issue,
            author=author,
            active_options=active_options
        )


class PartialMerge(TemplateException):
    code = 126
    template = 'partial_merge.md'
    dont_repeat_if_in_history = 0  # allow repeating as many times as it occurs
    status = "success"


class QueueOutOfOrder(TemplateException):
    code = 127
    template = "queue_out_of_order.md"
    status = "failure"


class ResetComplete(TemplateException):
    code = 128
    template = "reset_complete.md"


class LossyResetWarning(TemplateException):
    code = 129
    template = "lossy_reset.md"
    status = "failure"


class IncorrectCommandSyntax(TemplateException):
    code = 130
    template = "incorrect_command_syntax.md"
    status = "failure"


class IncorrectPullRequestNumber(TemplateException):
    code = 131
    template = "incorrect_pull_request_number.md"
    status = "failure"


class SourceBranchTooOld(TemplateException):
    code = 132
    template = "source_branch_too_old.md"
    status = "failure"


class FlakyGitHost(TemplateException):
    code = 133
    template = "flaky_git_host.md"
    status = "failure"


class NotAuthor(TemplateException):
    code = 134
    template = "not_author.md"
    status = "failure"


class RequestIntegrationBranches(TemplateException):
    code = 135
    template = "request_integration_branches.md"
    # TODO: review if it should be failure.
    status = "queued"


class QueueBuildFailedMessage(TemplateException):
    code = 136
    template = "queue_build_failed.md"


# internal exceptions
class UnableToSendEmail(InternalException):
    code = 201


class ImproperEmailFormat(InternalException):
    code = 202


class BranchNameInvalid(InternalException):
    code = 203

    def __init__(self, name):
        msg = 'Invalid name: %r' % name
        super(BranchNameInvalid, self).__init__(msg)


class ReleaseAlreadyExists(InternalException):
    code = 204

    def __init__(self, branch, tag):
        msg = 'Branch %r must be deleted as %r has been created, ' \
              'you must use a hotfix branch if you really intend ' \
              'to target this version.' \
              % (branch, tag)
        super(ReleaseAlreadyExists, self).__init__(msg)


class UnrecognizedBranchPattern(InternalException):
    code = 207


class JiraUnknownIssueType(InternalException):
    code = 209

    def __init__(self, issue_type):
        msg = ("Jira issue: unknown type %r" % issue_type)
        super(JiraUnknownIssueType, self).__init__(msg)


class DevBranchesNotSelfContained(InternalException):
    code = 210

    def __init__(self, upstream_branch, downstream_branch):
        msg = ("The git repository appears to be in a bad shape. "
               "Branch `%s` is not included in branch `%s`." % (
                   upstream_branch, downstream_branch))
        super(DevBranchesNotSelfContained, self).__init__(msg)


class DevBranchDoesNotExist(InternalException):
    code = 211

    def __init__(self, branch):
        msg = ("The git repository appears to be in a bad shape. "
               "Branch `%s` does not exist." % branch)
        super(DevBranchDoesNotExist, self).__init__(msg)


class NotASingleDevBranch(InternalException):
    code = 212

    def __init__(self):
        msg = ("The git repository appears to be in a bad shape. "
               "There is not a single development to merge to.")
        super(NotASingleDevBranch, self).__init__(msg)


class PullRequestSkewDetected(InternalException):
    code = 213

    def __init__(self, pr_id, local_sha1, pr_sha1):
        msg = "The pull request %d contains a more recent commit " \
              "than I expected (expected %s, got %s)" \
              % (pr_id, local_sha1, pr_sha1)
        super(PullRequestSkewDetected, self).__init__(msg)


class IncoherentQueues(InternalException):
    code = 214

    def __init__(self, errors):
        """Display errors as a list, with error code included
        for easy parsing in tests and easy lookup in code.

        """
        msg = 'The queues are in an incoherent state, ' \
              'I will block until the following points are resolved:\n' + \
              '\n'.join([" - [{code}] {label}".format(code=error.code,
                                                      label=error.msg)
                         for error in errors])
        super(IncoherentQueues, self).__init__(msg)


class InvalidQueueBranch(InternalException):
    code = 215

    def __init__(self, branch):
        msg = "This is not a queue branch:" \
              "%s" % (branch)
        super(InvalidQueueBranch, self).__init__(msg)


class QueuesNotValidated(InternalException):
    code = 216

    def __init__(self):
        msg = "The queues have not been validated, can't use them."
        super(QueuesNotValidated, self).__init__(msg)


class UnsupportedTokenType(InternalException):
    code = 217

    def __init__(self, token):
        msg = "The input token %r is not supported." % token
        super(UnsupportedTokenType, self).__init__(msg)


class SettingsFileNotFound(InternalException):
    code = 218

    def __init__(self, filename):
        msg = "Cannot find the settings file at %r." % filename
        super(SettingsFileNotFound, self).__init__(msg)


class IncorrectSettingsFile(InternalException):
    code = 219

    def __init__(self, filename):
        msg = "Cannot parse the settings file at %r." % filename
        super().__init__(msg)


class MalformedSettings(InternalException):
    code = 220

    def __init__(self, filename, errors, data):
        msg = "One or more errors were found while parsing {!r}:\n{}".format(
            filename, errors
        )
        super().__init__(msg)


class TaskAPIError(InternalException):
    code = 221

    def __init__(self, method, err):
        msg = "There was an error while accessing the task " \
              "API %r (%s)" % (method, err)
        super(TaskAPIError, self).__init__(msg)


class WrongDestination(TemplateException):
    code = 222
    template = 'incorrect_destination.md'


class QueueValidationError(Exception):
    """Extend simple string class with an error code and recovery potential."""
    code = 'Q000'
    auto_recovery = False  # set to True to let Bert-E fix the problem alone

    def __init__(self, msg):
        self.msg = msg
        super(QueueValidationError, self).__init__(msg)


class MasterQueueMissing(QueueValidationError):
    code = 'Q001'
    auto_recovery = False

    @staticmethod
    def _format_version(version):
        if not version:
            return '[]'
        if len(version) == 1 or (len(version) > 1 and version[1] is None):
            return f"{version[0]}"
        if len(version) == 2 or (len(version) > 2 and version[2] is None):
            return f"{version[0]}.{version[1]}"
        return f"{version[0]}.{version[1]}.{version[2]}"

    def __init__(self, version):
        version_str = self._format_version(version)
        msg = "there are integration queues on " \
            f"this version but q/{version_str} is missing"
        super().__init__(msg)


class MasterQueueLateVsDev(QueueValidationError):
    code = 'Q002'
    auto_recovery = False

    def __init__(self, masterq, dev):
        msg = '{masterq} is late ' \
              'compared to {dev}'.format(**locals())
        super(MasterQueueLateVsDev, self).__init__(msg)


class MasterQueueNotInSync(QueueValidationError):
    code = 'Q003'
    auto_recovery = False

    def __init__(self, masterq, dev):
        msg = 'no pending integration ' \
              'queues, yet {masterq} is not in sync ' \
              'with {dev}'.format(**locals())
        super(MasterQueueNotInSync, self).__init__(msg)


class MasterQueueLateVsInt(QueueValidationError):
    code = 'Q004'
    auto_recovery = False

    def __init__(self, masterq, intq):
        msg = '{masterq} is more recent ' \
              'than greatest integration queue ' \
              '{intq}'.format(**locals())
        super(MasterQueueLateVsInt, self).__init__(msg)


class MasterQueueYoungerThanInt(QueueValidationError):
    code = 'Q005'
    auto_recovery = False

    def __init__(self, masterq, intq):
        msg = 'greatest integration queue {intq} ' \
              'is late compared to {masterq}'.format(**locals())
        super(MasterQueueYoungerThanInt, self).__init__(msg)


class MasterQueueDiverged(QueueValidationError):
    code = 'Q006'
    auto_recovery = False

    def __init__(self, masterq, intq):
        msg = '{masterq} and greatest ' \
              'integration queue {intq} have ' \
              'diverged'.format(**locals())
        super(MasterQueueDiverged, self).__init__(msg)


class QueueInclusionIssue(QueueValidationError):
    code = 'Q007'
    auto_recovery = False

    def __init__(self, nextq, intq):
        msg = '{intq} is not included in ' \
              '{nextq}'.format(**locals())
        super(QueueInclusionIssue, self).__init__(msg)


class QueueInconsistentPullRequestsOrder(QueueValidationError):
    code = 'Q008'
    auto_recovery = False

    def __init__(self):
        msg = 'The order of integration queues with respect to ' \
              'the pull requests appears to be incorrect'
        super(QueueInconsistentPullRequestsOrder, self).__init__(msg)


class QueueIncomplete(QueueValidationError):
    code = 'Q009'
    auto_recovery = False

    def __init__(self):
        msg = 'An integration queue is missing'
        super(QueueIncomplete, self).__init__(msg)


# silent exceptions
class CommentAlreadyExists(SilentException):
    code = 300


class NotMyJob(SilentException):
    code = 301


class NothingToDo(SilentException):
    code = 302


class BuildInProgress(SilentException):
    code = 303
    status = "in_progress"


class BuildNotStarted(SilentException):
    code = 304


class PullRequestDeclined(SilentException):
    code = 305


class Merged(SilentException):
    code = 306


class JobSuccess(SilentException):
    code = 307


class JobFailure(SilentException):
    code = 308


class QueueBuildFailed(SilentException):
    code = 309
