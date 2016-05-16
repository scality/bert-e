#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
from collections import OrderedDict
import itertools
import logging
import re
import sys

from jira.exceptions import JIRAError
import requests
import six

from template_loader import render
import bitbucket_api
from git_api import (Repository as GitRepository,
                     Branch,
                     MergeFailedException,
                     CheckoutFailedException,
                     RemoveFailedException,
                     PushFailedException)
import jira_api
from wall_e_exceptions import (AfterPullRequest,
                               AuthorApprovalRequired,
                               BranchHistoryMismatch,
                               BranchNameInvalid,
                               BuildFailed,
                               BuildInProgress,
                               BuildNotStarted,
                               CommandNotImplemented,
                               CommentAlreadyExists,
                               Conflict,
                               DevBranchDoesNotExist,
                               DevBranchesNotSelfContained,
                               DeprecatedStabilizationBranch,
                               HelpMessage,
                               IncompatibleSourceBranchPrefix,
                               IncorrectFixVersion,
                               IncorrectJiraProject,
                               InitMessage,
                               IntegrationPullRequestsCreated,
                               IntegrationBranchNotCreated,
                               IntegrationPRNotCreated,
                               JiraIssueNotFound,
                               JiraUnknownIssueType,
                               MismatchPrefixIssueType,
                               MissingJiraId,
                               NotASingleDevBranch,
                               NothingToDo,
                               NotEnoughCredentials,
                               NotMyJob,
                               ParentPullRequestNotFound,
                               PullRequestSkewDetected,
                               SubtaskIssueNotSupported,
                               PeerApprovalRequired,
                               ReadyForMerge,
                               StatusReport,
                               SuccessMessage,
                               TesterApprovalRequired,
                               UnanimityApprovalRequired,
                               UnknownCommand,
                               UnrecognizedBranchPattern,
                               UnsupportedMultipleStabBranches,
                               VersionMismatch,
                               WallE_DryRun,
                               WallE_SilentException,
                               WallE_TemplateException,
                               WaitOptionIsSet)
from utils import RetryHandler

if six.PY3:
    raw_input = input
    unicode = six.text_type

WALL_E_USERNAME = 'scality_wall-e'
WALL_E_EMAIL = 'wall_e@scality.com'
JENKINS_USERNAME = 'scality_jenkins'

SETTINGS = {
    'ring': {
        'jira_key': 'RING',
        'build_key': 'pipeline',
        'testers': [
            WALL_E_USERNAME,  # we need this for test purposes
            'anneharper',
            'bjorn_schuberg',
            'christophe_meron',
            'christophe_stoyanov',
            'louis_pery_scality',
            'mcolzi',
            'romain_thebaud',
            'sleibo',
        ],
        'admins': [
            WALL_E_USERNAME,  # we need this for test purposes
            'alexander_garthwaite',
            'benoit_a',
            'flavienlebarbe',
            'jienhua',
            'jm_saffroy_scality',
            'nicolast_scality',
            'quentin_jacquemart',
            'xavier_roche',
            # RELENG below
            'anneharper',
            'bertrand_demiddelaer_scality',
            'ludovicmaillard',
            'mcolzi',
            'mvaude',
            'nohar',
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
        ]
    },
    'wall-e': {
        'jira_key': 'RELENG',
        'build_key': 'pipeline',
        'testers': [
        ],
        'admins': [
            'ludovicmaillard',
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
        ]
    },
    'gollum': {
        'jira_key': 'RELENG',
        'build_key': 'pipeline',
        'testers': [
        ],
        'admins': [
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
        ]
    },
    'releng-jenkins': {
        'jira_key': 'RELENG',
        'build_key': 'pipeline',
        'testers': [
        ],
        'admins': [
            'bertrand_demiddelaer_scality',
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
        ]
    },
    'wall-e-demo': {
        'jira_key': 'DEMOWALLE',
        'build_key': 'pipeline',
        'testers': [
        ],
        'admins': [
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian',
            'mvaude',
        ]
    }
}

JIRA_ISSUE_BRANCH_PREFIX = {
    'Epic': 'project',
    'Story': 'feature',
    'Bug': 'bugfix',
    'Improvement': 'improvement'
}


class Option(object):
    """Wall-E options implementation.

    Wall-E uses options to activate additional functionality
    or alter the behaviour of existing functionality.

    An option is always set to False by default.

    It is activated either on the command line of wall_e.py,
    or by the users of a pull-request, by adding a special
    comment in the pull-request. The options then remain
    active until this comment is deleted.

    An option may require privileges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, privileged, help, value=False):
        self.value = value
        self.help = help
        self.privileged = privileged

    def set(self, value):
        self.value = value

    def is_set(self):
        return self.value

    def __repr__(self):
        return "<%s, %s>" % (self.value, "admin" if self.privileged else "any")


class Command(object):
    """Wall-E commands implementation.

    Wall-E uses commands to operate one-time actions.

    Commands are triggered by adding a comment in the
    pull-request.

    A command may require privileges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, privileged, help, handler):
        self.handler = handler
        self.help = help
        self.privileged = privileged


def confirm(question):
    input_ = raw_input(question + " Enter (y)es or (n)o: ")
    return input_ == "yes" or input_ == "y"


class WallEBranch(Branch):
    pattern = '(?P<prefix>[a-z]+)/(?P<label>.+)'
    major = 0
    minor = 0
    micro = -1  # is incremented always, first version is 0
    cascade_producer = False
    cascade_consumer = False
    can_be_destination = False
    allow_ticketless_pr = False

    def __init__(self, repo, name):
        super(WallEBranch, self).__init__(repo, name)
        match = re.match(self.pattern, name)
        if not match:
            raise BranchNameInvalid(name)
        for key, value in match.groupdict().items():
            if key in ('major', 'minor', 'micro') and value is not None:
                value = int(value)
            self.__setattr__(key, value)

    def __str__(self):
        return self.name

    def __unicode__(self):
        return self.name


class HotfixBranch(WallEBranch):
    pattern = '^hotfix/(?P<label>.+)$'


class UserBranch(WallEBranch):
    pattern = '^user/(?P<label>.+)$'
    allow_ticketless_pr = True


class ReleaseBranch(WallEBranch):
    pattern = '^release/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'


class FeatureBranch(WallEBranch):
    correction_prefixes = ('improvement', 'bugfix')
    all_prefixes = ('improvement', 'bugfix', 'feature', 'project')
    jira_issue_pattern = '(?P<jira_project>[A-Z0-9_]+)-[0-9]+'
    prefixes = '(?P<prefix>(%s))' % '|'.join(all_prefixes)
    pattern = "^%s/(?P<label>(?P<jira_issue_key>%s)?" \
              "(?(jira_issue_key).*|.+))$" % (prefixes, jira_issue_pattern)
    cascade_producer = True
    allow_ticketless_pr = True


class DevelopmentBranch(WallEBranch):
    pattern = '^development/(?P<version>(?P<major>\d+)\.(?P<minor>\d+))$'
    cascade_producer = True
    cascade_consumer = True
    can_be_destination = True
    allow_prefixes = FeatureBranch.correction_prefixes

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
            self.major == other.major and \
            self.minor == other.minor


class StabilizationBranch(DevelopmentBranch):
    pattern = '^stabilization/' \
              '(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+))$'
    allow_prefixes = FeatureBranch.correction_prefixes

    def __eq__(self, other):
        return DevelopmentBranch.__eq__(self, other) and \
            self.micro == other.micro


class IntegrationBranch(WallEBranch):
    pattern = '^w/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)' \
              '(\.(?P<micro>\d+))?)/' + FeatureBranch.pattern[1:]
    destination_branch = ''
    source_branch = ''

    def merge_from_branch(self, source_branch, dry_run):
        self.merge(source_branch, do_push=(not dry_run))

    def update_to_development_branch(self):
        self.destination_branch.merge(self, force_commit=False)
        self.destination_branch.push()

    def _get_pull_request_from_list(self, open_prs):
        pr = None
        for pr_ in open_prs:
            if pr_['source']['branch']['name'] != self.name:
                continue
            if pr_['destination']['branch']['name'] != \
                    self.destination_branch.name:
                continue
            pr = pr_
            break
        return pr

    def get_or_create_pull_request(self, parent_pr, open_prs, bitbucket_repo,
                                   dry_run, first=False):
        title = bitbucket_api.fix_pull_request_title(
            'INTEGRATION [PR#%s > %s] %s' % (
                parent_pr['id'],
                self.destination_branch.name,
                parent_pr['title']
            )
        )

        # WARNING potential infinite loop:
        # creating a child pr will trigger a 'pr update' webhook
        # wall-e will analyse it, retrieve the main pr, then
        # re-enter here and recreate the children pr.
        # solution: do not create the pr if it already exists
        pr = self._get_pull_request_from_list(open_prs)
        # need a boolean to know if the PR is created or no
        created = False
        if not pr:
            if dry_run:
                raise IntegrationPRNotCreated()
            description = render('pull_request_description.md',
                                 wall_e=WALL_E_USERNAME,
                                 pr=parent_pr,
                                 branch=self.name,
                                 first=first)
            pr = bitbucket_repo.create_pull_request(
                title=title,
                name='name',
                source={'branch': {'name': self.name}},
                destination={'branch': {'name': self.destination_branch.name}},
                close_source_branch=True,
                reviewers=[{'username': parent_pr['author']['username']}],
                description=description)
            created = True
        return pr, created


def branch_factory(repo, branch_name):
    for cls in [StabilizationBranch, DevelopmentBranch, ReleaseBranch,
                FeatureBranch, HotfixBranch, IntegrationBranch, UserBranch]:
        try:
            branch = cls(repo, branch_name)
            return branch
        except BranchNameInvalid:
            pass

    raise UnrecognizedBranchPattern(branch_name)


class BranchCascade(object):
    def __init__(self):
        self._cascade = OrderedDict()
        self.destination_branches = []  # store branches
        self.ignored_branches = []  # store branch names (easier sort)
        self.target_versions = []

    def add_branch(self, branch):
        if not branch.can_be_destination:
            logging.debug("Discard non destination branch: %s", branch)
            return
        (major, minor) = branch.major, branch.minor
        if (major, minor) not in self._cascade.keys():
            self._cascade[(major, minor)] = {
                DevelopmentBranch: None,
                StabilizationBranch: None,
            }
            # Sort the cascade again
            self._cascade = OrderedDict(sorted(self._cascade.items()))
        cur_branch = self._cascade[(major, minor)][branch.__class__]

        if cur_branch:
            raise UnsupportedMultipleStabBranches(cur_branch, branch)

        self._cascade[(major, minor)][branch.__class__] = branch

    def update_micro(self, tag):
        """Update development branch latest micro based on tag."""
        pattern = "^(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<micro>\d+))$"
        match = re.match(pattern, tag)
        if not match:
            logging.debug("Ignore tag: %s", tag)
            return
        logging.debug("Consider tag: %s", tag)
        major = int(match.groupdict()['major'])
        minor = int(match.groupdict()['minor'])
        micro = int(match.groupdict()['micro'])
        try:
            branches = self._cascade[(major, minor)]
        except KeyError:
            logging.debug("Ignore tag: %s", tag)
            return
        stb_branch = branches[StabilizationBranch]

        if stb_branch is not None and stb_branch.micro <= micro:
            # We have a tag but we did not remove the stabilization branch.
            raise DeprecatedStabilizationBranch(stb_branch.name, tag)

        dev_branch = branches[DevelopmentBranch]
        if dev_branch:
            dev_branch.micro = max(micro, dev_branch.micro)

    def validate(self):
        previous_dev_branch = None
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if dev_branch is None:
                raise DevBranchDoesNotExist(
                    'development/%d.%d' % (major, minor))

            if stb_branch:
                if dev_branch.micro != stb_branch.micro + 1:
                    raise VersionMismatch(dev_branch, stb_branch)

                if not dev_branch.includes_commit(stb_branch):
                    raise DevBranchesNotSelfContained(stb_branch, dev_branch)

            if previous_dev_branch:
                if not dev_branch.includes_commit(previous_dev_branch):
                    raise DevBranchesNotSelfContained(previous_dev_branch,
                                                      dev_branch)

            previous_dev_branch = dev_branch

    def _set_target_versions(self, destination_branch):
        """Compute list of expected Jira FixVersion/s.

        Must be called after the cascade has been finalised.

        """
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if stb_branch:
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, stb_branch.micro))
            else:
                self.target_versions.append('%d.%d.%d' % (
                    major, minor, dev_branch.micro))

    def finalize(self, destination_branch):
        """Finalize cascade considering given destination.

        Assumes the cascade has been populated by calls to add_branch
        and update_micro. The local lists keeping track

        Args:
            destination_branch: where the pull request wants to merge

        Raises:

        Returns:
            list: list of destination branches
            list: list of ignored destination branches

        """
        ignore_stb_branches = False
        include_dev_branches = False
        dev_branch = None

        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            stb_branch = branch_set[StabilizationBranch]

            if dev_branch is None:
                raise DevBranchDoesNotExist(
                    'development/%d.%d' % (major, minor))

            # update _expected_ micro versions
            if stb_branch:
                dev_branch.micro += 2
            else:
                dev_branch.micro += 1

            # remove untargetted branches from cascade
            if destination_branch == dev_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if stb_branch and ignore_stb_branches:
                branch_set[StabilizationBranch] = None
                self.ignored_branches.append(stb_branch.name)

            if destination_branch == stb_branch:
                include_dev_branches = True
                ignore_stb_branches = True

            if not include_dev_branches:
                branch_set[DevelopmentBranch] = None
                self.ignored_branches.append(dev_branch.name)

                if branch_set[StabilizationBranch]:
                    branch_set[StabilizationBranch] = None
                    self.ignored_branches.append(stb_branch.name)

                del self._cascade[(major, minor)]
                continue

            # add to destination_branches in the correct order
            if branch_set[StabilizationBranch]:
                self.destination_branches.append(stb_branch)
            if branch_set[DevelopmentBranch]:
                self.destination_branches.append(dev_branch)

        if not dev_branch:
            raise NotASingleDevBranch()

        self._set_target_versions(destination_branch)
        self.ignored_branches.sort()

        # the last dev branch accepts ticketless pull requests,
        # and any type of ticket type
        dev_branch.allow_ticketless_pr = True
        dev_branch.allow_prefixes = FeatureBranch.all_prefixes


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail,
                 owner, slug, pull_request_id, options, commands, settings,
                 dry_run):
        self._bbconn = bitbucket_api.Client(
            bitbucket_login, bitbucket_password, bitbucket_mail)
        self.bbrepo = bitbucket_api.Repository(
            self._bbconn, owner=owner, repo_slug=slug)
        self.main_pr = self.bbrepo.get_pull_request(
            pull_request_id=pull_request_id)
        self.author = self.main_pr['author']['username']
        self.author_display_name = self.main_pr['author']['display_name']
        if WALL_E_USERNAME == self.author:
            res = re.search('(?P<pr_id>\d+)',
                            self.main_pr['description'])
            if not res:
                raise ParentPullRequestNotFound(self.main_pr['id'])
            self.pull_request_id = int(res.group('pr_id'))
            self.main_pr = self.bbrepo.get_pull_request(
                pull_request_id=self.pull_request_id
            )
            self.author = self.main_pr['author']['username']
            self.author_display_name = self.main_pr['author']['display_name']
        self.options = options
        self.commands = commands
        self.settings = settings
        self.source_branch = None
        self.destination_branch = None
        self._cascade = BranchCascade()
        self.after_prs = []
        # first posted comments first in the list
        self.comments = []
        self.dry_run = dry_run

    def option_is_set(self, name):
        if name not in self.options.keys():
            return False
        return self.options[name].is_set()

    def _get_active_options(self):
        return [option for option in self.options.keys() if
                self.option_is_set(option)]

    def print_help(self, args):
        raise HelpMessage(options=self.options,
                          commands=self.commands,
                          active_options=self._get_active_options())

    def get_status_report(self):
        # tmp hard coded
        return {}

    def publish_status_report(self, args):
        raise StatusReport(status=self.get_status_report(),
                           active_options=self._get_active_options())

    def command_not_implemented(self, args):
        raise CommandNotImplemented(
            active_options=self._get_active_options()
        )

    def find_bitbucket_comment(self,
                               username=None,
                               startswith=None,
                               max_history=None):
        # check last commits
        comments = reversed(self.comments)
        if max_history not in (None, -1):
            comments = itertools.islice(comments, 0, max_history)
        for comment in comments:
            u = comment['user']['username']
            raw = comment['content']['raw']
            # python3
            if isinstance(username, str) and u != username:
                continue
            # python2
            if isinstance(username, list) and u not in username:
                continue
            if startswith and not raw.startswith(startswith):
                if max_history == -1:
                    return
                continue
            return comment

    def send_bitbucket_msg(self, msg, no_comment=False,
                           dont_repeat_if_in_history=10,
                           interactive=False):
        logging.debug('considering sending: %s', msg)

        if no_comment:
            logging.debug('not sending message due to no_comment being True.')
            return

        # if wall-e doesn't do anything in the last 10 comments,
        # allow him to run again
        if dont_repeat_if_in_history:
            if self.find_bitbucket_comment(
                    username=WALL_E_USERNAME,
                    startswith=msg,
                    max_history=dont_repeat_if_in_history):
                raise CommentAlreadyExists('The same comment has '
                                           'already been posted by '
                                           'Wall-E in the past. '
                                           'Nothing to do here!')

        if interactive:
            print('%s\n' % msg)
            if not confirm('Do you want to send this comment?'):
                return

        logging.debug('SENDING MSG %s', msg)

        if self.dry_run:
            return

        self.main_pr.add_comment(msg)

    def _check_pr_state(self):
        if self.main_pr['state'] != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDo('The pull-request\'s state is "%s"'
                              % self.main_pr['state'])

    def _clone_git_repo(self, reference_git_repo):
        git_repo = GitRepository(self.bbrepo.get_git_url(), '/tmp/ring')
        git_repo.cmd_directory = '/tmp/ring'
        #git_repo.clone(reference_git_repo)
        #git_repo.fetch_all_branches()
        #git_repo.config('user.email', WALL_E_EMAIL)
        #git_repo.config('user.name', WALL_E_USERNAME)
        #git_repo.config('merge.renameLimit', '999999')
        return git_repo

    def _setup_source_branch(self, repo, src_branch_name, dst_branch_name):
        self.source_branch = branch_factory(repo, src_branch_name)

    def _setup_destination_branch(self, repo, dst_branch_name):
        self.destination_branch = branch_factory(repo, dst_branch_name)

    def _check_if_ignored(self):
        # check feature branch
        if not self.source_branch.cascade_producer:
            raise NotMyJob(self.source_branch.name,
                           self.destination_branch.name)

        # check selected destination branch
        if not self.destination_branch.cascade_consumer:
            raise NotMyJob(self.source_branch.name,
                           self.destination_branch.name)

    def _send_greetings(self):
        """Display a welcome message if conditions are met."""
        for comment in self.comments:
            author = comment['user']['username']
            if isinstance(author, list):
                # python2 returns a list
                if len(author) != 1:
                    continue
                author = author[0]

            if author == WALL_E_USERNAME:
                return

        raise InitMessage(author=self.author_display_name,
                          status=self.get_status_report(),
                          active_options=self._get_active_options())

    def _check_options(self, comment_author, pr_author, keyword_list, comment):
        logging.debug('checking keywords %s', keyword_list)

        for idx, keyword in enumerate(keyword_list):
            if keyword.startswith('after_pull_request='):
                match_ = re.match('after_pull_request=(?P<pr_id>\d+)$',
                                  keyword)
                if not match_:
                    return False
                self.after_prs.append(match_.group('pr_id'))
                keyword = 'after_pull_request'

            if keyword not in self.options.keys():
                # the first keyword may be a valid command
                if idx == 0 and keyword in self.commands:
                    logging.debug("ignoring options due to unknown keyword")
                    return False

                raise UnknownCommand(active_options=self._get_active_options(),
                                     command=keyword,
                                     author=comment_author,
                                     comment=comment)

            limited_access = self.options[keyword].privileged
            if limited_access:
                if comment_author == pr_author:
                    raise NotEnoughCredentials(
                        active_options=self._get_active_options(),
                        command=keyword,
                        author=comment_author,
                        self_pr=True,
                        comment=comment
                    )

                if comment_author not in self.settings['admins']:
                    raise NotEnoughCredentials(
                        active_options=self._get_active_options(),
                        command=keyword,
                        author=comment_author,
                        self_pr=False,
                        comment=comment
                    )

        return True

    def _get_options(self, pr_author):
        """Load settings from pull-request comments."""
        for comment in self.comments:
            raw = comment['content']['raw']
            if not raw.strip().startswith('@%s' % WALL_E_USERNAME):
                continue

            logging.debug('Found a keyword comment: %s', raw)
            raw_cleaned = raw.strip()[len(WALL_E_USERNAME) + 1:]

            author = comment['user']['username']
            if isinstance(author, list):
                # python2 returns a list
                if len(author) != 1:
                    continue
                author = author[0]

            # accept all options in the form:
            # @scality_wall-e option1 option2...
            # @scality_wall-e option1, option2, ...
            # @scality_wall-e: option1 - option2 - ...
            raw_cleaned = re.sub(r'[,.\-/:;|+]', ' ', raw_cleaned)
            regexp = r"\s*(?P<keywords>(\s+[\w=]+)+)\s*$"
            match_ = re.match(regexp, raw_cleaned)
            if not match_:
                logging.debug('Keyword comment ignored. '
                              'Not an option, unknown format: %s', raw)
                continue

            keywords = match_.group('keywords').strip().split()

            if not self._check_options(author, pr_author, keywords, raw):
                logging.debug('Keyword comment ignored. '
                              'Not an option, checks failed: %s', raw)
                continue

            for keyword in keywords:
                # strip args
                option = keyword.split('=')[0]
                self.options[option].set(True)

    def _check_command(self, author, command, comment):
        logging.debug('checking command %s', command)

        if command not in self.commands:
            if command in self.options:
                logging.debug("Ignoring option")
                return False
            # Should not happen because of previous option check,
            # better be safe than sorry though
            raise UnknownCommand(active_options=self._get_active_options(),
                                 command=command,
                                 author=author,
                                 comment=comment)

        limited_access = self.commands[command].privileged
        if limited_access and author not in self.settings['admins']:
            raise NotEnoughCredentials(
                active_options=self._get_active_options(),
                command=command,
                author=author,
                self_pr=False,
                comment=comment
            )
        return True

    def _handle_commands(self):
        """Detect the last command in pull-request comments and act on it."""
        for comment in reversed(self.comments):
            author = comment['user']['username']
            if isinstance(author, list):
                # python2 returns a list
                if len(author) != 1:
                    continue
                author = author[0]

            # if Wall-E is the author of this comment, any previous command
            # has been treated or is outdated, since Wall-E replies to all
            # commands. The search is over.
            if author == WALL_E_USERNAME:
                return

            raw = comment['content']['raw']
            if not raw.strip().startswith('@%s' % WALL_E_USERNAME):
                continue

            logging.debug('Found a potential command comment: %s', raw)

            # accept all commands in the form:
            # @scality_wall-e command arg1 arg2 ...
            regexp = "@%s[\s:]*" % WALL_E_USERNAME
            raw_cleaned = re.sub(regexp, '', raw.strip())
            regexp = r"(?P<command>\w+)(?P<args>.*)$"
            match_ = re.match(regexp, raw_cleaned)
            if not match_:
                logging.warning('Command comment ignored. '
                                'Not a command, unknown format: %s' % raw)
                continue

            command = match_.group('command')

            if not self._check_command(author, command, raw):
                logging.debug('Command comment ignored. '
                              'Not a command, checks failed: %s' % raw)
                continue

            # get command handler and execute it
            assert hasattr(self, self.commands[command].handler)
            handler = getattr(self, self.commands[command].handler)
            handler(match_.group('args'))

    def _init_phase(self):
        """Send greetings if required, read options and commands."""
        # read comments and store them for multiple usage
        self.comments = list(self.main_pr.get_comments())
        if self.comments and self.comments[0]['id'] > self.comments[-1]['id']:
            self.comments.reverse()

        self._send_greetings()
        self._get_options(self.author)
        self._handle_commands()

    def _check_dependencies(self):
        if self.option_is_set('wait'):
            raise WaitOptionIsSet()

        if not self.after_prs:
            return

        prs = [self.bbrepo.get_pull_request(pull_request_id=int(x))
               for x in self.after_prs]

        opened_prs = filter(lambda x: x['state'] == 'OPEN', prs)
        merged_prs = filter(lambda x: x['state'] == 'MERGED', prs)
        declined_prs = filter(lambda x: x['state'] == 'DECLINED', prs)

        if len(self.after_prs) != len(merged_prs):
            raise AfterPullRequest(
                opened_prs=opened_prs,
                declined_prs=declined_prs,
                active_options=self._get_active_options())

    def _build_branch_cascade(self, git_repo):
        for prefix in ['development', 'stabilization']:
            cmd = 'git branch -r --list origin/%s/*' % prefix
            for branch in git_repo.cmd(cmd).split('\n')[:-1]:
                match_ = re.match('\s*origin/(?P<name>.*)', branch)
                if not match_:
                    continue
                try:
                    branch = branch_factory(git_repo, match_.group('name'))
                except UnrecognizedBranchPattern:
                    continue
                self._cascade.add_branch(branch)

        for tag in git_repo.cmd('git tag').split('\n')[:-1]:
            self._cascade.update_micro(tag)

        self._cascade.finalize(self.destination_branch)

    def _check_compatibility_src_dest(self):
        if self.option_is_set('bypass_incompatible_branch'):
            return
        for dest_branch in self._cascade.destination_branches:
            if self.source_branch.prefix not in dest_branch.allow_prefixes:
                raise IncompatibleSourceBranchPrefix(
                    source=self.source_branch,
                    destination=self.destination_branch,
                    active_options=self._get_active_options())

    def _jira_check_reference(self):
        """Check the reference to a Jira issue in the source branch.

        Returns:
            bool: True if the reference is valid and must be checked
                  False if the Jira issue should be ignored

        Raises:
            MissingJiraId: if a Jira issue is required but missing

        """
        if not self.source_branch.jira_issue_key:
            for dest_branch in self._cascade.destination_branches:
                if not dest_branch.allow_ticketless_pr:
                    raise MissingJiraId(
                        source_branch=self.source_branch.name,
                        dest_branch=dest_branch.name,
                        active_options=self._get_active_options())
            return False
        return True

    def _jira_get_issue(self, issue_id):
        try:
            issue = jira_api.JiraIssue(issue_id=issue_id, login='wall_e',
                                       passwd=self._bbconn.auth.password)
        except JIRAError as e:
            if e.status_code == 404:
                raise JiraIssueNotFound(
                    issue=issue_id,
                    active_options=self._get_active_options())

            else:
                raise

        return issue

    def _jira_check_project(self, issue):
        # check the project
        if (self.source_branch.jira_project !=
                self.settings['jira_key']):
            raise IncorrectJiraProject(
                expected_project=self.settings['jira_key'],
                issue=issue,
                active_options=self._get_active_options()
            )

    def _jira_check_issue_type(self, issue):
        issuetype = issue.fields.issuetype.name

        if issuetype == 'Sub-task':
            raise SubtaskIssueNotSupported(
                issue=issue,
                pairs=JIRA_ISSUE_BRANCH_PREFIX,
                active_options=self._get_active_options())

        expected_prefix = JIRA_ISSUE_BRANCH_PREFIX.get(issuetype)
        if expected_prefix is None:
            raise JiraUnknownIssueType(issuetype)

        if expected_prefix != self.source_branch.prefix:
            raise MismatchPrefixIssueType(
                prefix=self.source_branch.prefix,
                expected=issuetype,
                pairs=JIRA_ISSUE_BRANCH_PREFIX,
                issue=issue,
                active_options=self._get_active_options())

    def _jira_check_version(self, issue):
        issue_versions = [version.name for version in
                          issue.fields.fixVersions]
        issue_versions.sort()
        issue_versions = set(issue_versions)
        expect_versions = self._cascade.target_versions
        expect_versions.sort()
        expect_versions = set(expect_versions)

        if issue_versions != expect_versions:
            raise IncorrectFixVersion(
                issue=issue,
                issue_versions=issue_versions,
                expect_versions=expect_versions,
                active_options=self._get_active_options())

    def _jira_checks(self):
        """Check the Jira issue id specified in the source branch."""
        if self.option_is_set('bypass_jira_check'):
            return

        if not self.settings['jira_key']:
            return

        if self._jira_check_reference():
            issue_id = self.source_branch.jira_issue_key
            issue = self._jira_get_issue(issue_id)

            self._jira_check_project(issue)
            self._jira_check_issue_type(issue)
            self._jira_check_version(issue)

    def _check_source_branch_still_exists(self, git_repo):
        # check source branch still exists
        # (it may have been deleted by developers)
        try:
            Branch(git_repo, self.source_branch.name).checkout()
        except CheckoutFailedException:
            raise NothingToDo(self.source_branch.name)

    def _create_integration_branches(self, repo, source_branch):
        integration_branches = []
        for dst_branch in self._cascade.destination_branches:
            name = 'w/%s/%s' % (dst_branch.version, source_branch)
            integration_branch = branch_factory(repo, name)
            integration_branch.source_branch = source_branch
            integration_branch.destination_branch = dst_branch
            integration_branches.append(integration_branch)
            if not integration_branch.exists():
                if self.dry_run:
                    raise IntegrationBranchNotCreated()
                integration_branch.create(
                    integration_branch.destination_branch)
                integration_branch.push()
        return integration_branches

    def _check_history_did_not_change(self, integration_branch):
        development_branch = integration_branch.destination_branch
        for commit in integration_branch.get_all_commits(
                integration_branch.source_branch):
            if not development_branch.includes_commit(commit):
                raise BranchHistoryMismatch(
                    commit=commit,
                    integration_branch=integration_branch,
                    feature_branch=integration_branch.source_branch,
                    development_branch=development_branch,
                    active_options=self._get_active_options())

    def _update(self, source, destination, origin=False):
        try:
            # Retry for up to 60 seconds when connectivity is lost
            with RetryHandler(60, logging) as retry:
                retry.run(
                    destination.merge_from_branch, source, self.dry_run,
                    catch=PushFailedException,
                    fail_msg="Couldn't push merge (%s -> %s)" % (
                        source, destination
                    )
                )
        except MergeFailedException:
            raise Conflict(source=source,
                           destination=destination,
                           active_options=self._get_active_options(),
                           origin=origin)

    def _update_integration_from_dev(self, integration_branches):
        # The first integration branch should not contain commits
        # that are not in development/* or in the feature branch.
        first, children = integration_branches[0], integration_branches[1:]
        self._check_history_did_not_change(first)
        self._update(first.destination_branch, first, True)
        for integration_branch in children:
            self._update(
                integration_branch.destination_branch,
                integration_branch)

    def _update_integration_from_feature(self, integration_branches):
        first, children = integration_branches[0], integration_branches[1:]
        self._update(self.source_branch, first, True)
        branch_to_merge_from = first
        for integration_branch in children:
            self._update(branch_to_merge_from, integration_branch)
            branch_to_merge_from = integration_branch

    def _create_pull_requests(self, integration_branches):
        # read open PRs and store them for multiple usage
        open_prs = list(self.bbrepo.get_pull_requests())
        prs, created = zip(*(
            integration_branch.get_or_create_pull_request(self.main_pr,
                                                          open_prs,
                                                          self.bbrepo,
                                                          self.dry_run, idx == 0)
            for idx, integration_branch in enumerate(integration_branches)
        ))
        if any(created):
            raise IntegrationPullRequestsCreated(
                        pr=self.main_pr,
                        child_prs=prs,
                        ignored=self._cascade.ignored_branches,
                        active_options=self._get_active_options(),
                    )
        return prs

    def _check_pull_request_skew(self, integration_branches, integration_prs):
        """Check potential skew between local commit and commit in PR.

        Three cases are possible:
        - the local commit and the commit we obtained in the PR
          object are identical; nothing to do

        - the local commit, that has just been pushed by Wall-E,
          does not reflect yet in the PR object we obtained from
          bitbucket (the cache mechanism from BB mean the PR is still
          pointing to a previous commit); the solution is to update
          the PR object with the latest commit we know of

        - the local commit is outdated, someone else has pushed new
          commits on the integration branch, and it reflects in the PR
          object; in this case we abort the process, Wall-E will be
          called again on the new commits.

        """
        for branch, pr in zip(integration_branches, integration_prs):
            branch_sha1 = branch.get_latest_commit()  # short sha1
            pr_sha1 = pr['source']['commit']['hash']  # full sha1
            if pr_sha1.startswith(branch_sha1):
                continue

            if branch.includes_commit(pr_sha1):
                logging.warning('Skew detected (expected commit: %s, '
                                'got PR commit: %s).', branch_sha1,
                                pr_sha1[:12])
                logging.warning('Updating the integration PR locally.')
                pr['source']['commit']['hash'] = branch_sha1
                continue

            raise PullRequestSkewDetected(pr['id'], branch_sha1, pr_sha1)

    def _check_approvals(self, child_prs):
        """Check approval of a PR by author, tester and peer.

        Args:
            - child_prs (json): all the child PRs

        Raises:
            - AuthorApprovalRequired
            - PeerApprovalRequired
            - TesterApprovalRequired

        """
        approved_by_author = self.option_is_set('bypass_author_approval')
        approved_by_peer = self.option_is_set('bypass_peer_approval')
        approved_by_tester = self.option_is_set('bypass_tester_approval')
        requires_unanimity = self.option_is_set('unanimity')
        is_unanimous = True

        if not self.settings['testers']:
            # if the project does not declare any testers,
            # just assume a pseudo-tester has approved the PR
            approved_by_tester = True

        # If a tester is the author of the PR we will bypass
        #  the tester approval
        if self.author in self.settings['testers']:
            approved_by_tester = True

        if (approved_by_author and approved_by_peer and
                approved_by_tester and not requires_unanimity):
            return

        # NB: when author hasn't approved the PR, author isn't listed in
        # 'participants'
        for participant in self.main_pr['participants']:
            if not participant['approved']:
                # Exclude WALL_E and SCALITY_JENKINS
                if (not participant['user']['username'] in [WALL_E_USERNAME,
                                                            JENKINS_USERNAME]):
                    is_unanimous = False
                continue
            if participant['user']['username'] == self.author:
                approved_by_author = True
            elif participant['user']['username'] in self.settings['testers']:
                approved_by_tester = True
            else:
                approved_by_peer = True

        if not approved_by_author:
            raise AuthorApprovalRequired(
                pr=self.main_pr,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if not approved_by_peer:
            raise PeerApprovalRequired(
                pr=self.main_pr,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if not approved_by_tester:
            raise TesterApprovalRequired(
                pr=self.main_pr,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

        if (requires_unanimity and not is_unanimous):
            raise UnanimityApprovalRequired(
                pr=self.main_pr,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
                requires_unanimity=requires_unanimity,
                active_options=self._get_active_options()
            )

    def _get_pr_build_status(self, key, pr):
        try:
            build_state = self.bbrepo.get_build_status(
                revision=pr['source']['commit']['hash'],
                key=key
            )['state']
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return 'NOTSTARTED'
            else:
                raise
        return build_state

    def _check_build_status(self, child_prs):
        """Report the worst status available."""
        if self.option_is_set('bypass_build_status'):
            return

        key = self.settings['build_key']
        if not key:
            return

        ordered_state = ['SUCCESSFUL', 'INPROGRESS', 'NOTSTARTED', 'FAILED']
        g_state = 'SUCCESSFUL'
        worst_pr = child_prs[0]
        for pr in child_prs:
            build_state = self._get_pr_build_status(key, pr)
            if ordered_state.index(g_state) < ordered_state.index(build_state):
                g_state = build_state
                worst_pr = pr

        if g_state == 'FAILED':
            raise BuildFailed(pr_id=worst_pr['id'],
                              active_options=self._get_active_options())
        elif g_state == 'NOTSTARTED':
            raise BuildNotStarted()
        elif g_state == 'INPROGRESS':
            raise BuildInProgress()
        assert build_state == 'SUCCESSFUL'

    def _merge(self, integration_branches):
        # Retry for up to 5 minutes when connectivity is lost
        # Simply accepting failure here could lead to a messy situation
        retry = RetryHandler(300, logging)
        for integration_branch in integration_branches:
            with retry:
                retry.run(
                    integration_branch.update_to_development_branch,
                    catch=PushFailedException,
                    fail_msg="Failed to push merge of branch %s" % (
                        integration_branch
                    )
                )

        for integration_branch in integration_branches:
            try:
                integration_branch.remove()
            except RemoveFailedException:
                # ignore failures as this is non critical
                pass

    def _validate_repo(self):
        self._cascade.validate()

    def handle_pull_request(self, reference_git_repo='',
                            no_comment=False, interactive=False):

        self._check_pr_state()

        with self._clone_git_repo(reference_git_repo) as repo:
            dst_branch_name = self.main_pr['destination']['branch']['name']
            src_branch_name = self.main_pr['source']['branch']['name']
            self._setup_source_branch(repo, src_branch_name, dst_branch_name)
            self._setup_destination_branch(repo, dst_branch_name)

            # Handle the case when bitbucket is lagging and the PR was actually
            # merged before.
            if self.destination_branch.includes_commit(self.source_branch):
                raise NothingToDo()

            self._check_if_ignored()
            self._init_phase()
            self._check_dependencies()
            self._build_branch_cascade(repo)
            self._validate_repo()
            self._check_compatibility_src_dest()
            self._jira_checks()
            self._check_source_branch_still_exists(repo)

            integration_branches = self._create_integration_branches(
                repo, self.source_branch)

            if not self.dry_run:
                self._update_integration_from_dev(integration_branches)
                self._update_integration_from_feature(integration_branches)
            else:
                # should detect conflicts somehow
                pass
            child_prs = self._create_pull_requests(integration_branches)
            self._check_pull_request_skew(integration_branches, child_prs)
            self._check_approvals(child_prs)
            self._check_build_status(child_prs)

            if self.dry_run:
                raise ReadyForMerge()

            if interactive and not confirm('Do you want to merge ?'):
                return

            self._merge(integration_branches)
            self._validate_repo()

        raise SuccessMessage(
            branches=self._cascade.destination_branches,
            ignored=self._cascade.ignored_branches,
            issue=self.source_branch.jira_issue_key,
            author=self.author_display_name,
            active_options=self._get_active_options())


def setup_parser():
    parser = argparse.ArgumentParser(add_help=True,
                                     description='Merges bitbucket '
                                                 'pull requests.')
    parser.add_argument(
        '--option', '-o', action='append', type=str, dest='cmd_line_options',
        help="Activate additional options")
    parser.add_argument(
        'pull_request_id',
        help="The ID of the pull request")
    parser.add_argument(
        'password',
        help="Wall-E's password [for Jira and Bitbucket]")
    parser.add_argument(
        '--reference-git-repo', default='',
        help="Reference to a local git repo to improve cloning delay")
    parser.add_argument(
        '--owner', default='scality',
        help="The owner of the repo (default: scality)")
    parser.add_argument(
        '--slug', default='ring',
        help="The repo's slug (default: ring)")
    parser.add_argument(
        '--settings', default='',
        help="The settings to use (default to repository slug)")
    parser.add_argument(
        '--interactive', action='store_true', default=False,
        help="Ask before merging or sending comments")
    parser.add_argument(
        '--no-comment', action='store_true', default=False,
        help="Do not add any comment to the pull request page")
    parser.add_argument(
        '-v', action='store_true', dest='verbose', default=False,
        help="Verbose mode")
    parser.add_argument(
        '--backtrace', action='store_true', default=False,
        help="Show backtrace instead of return code on console")
    parser.add_argument(
        '--quiet', action='store_true', default=False,
        help="Don't print return codes on the console")
    parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help="Don't modify anything, just output current status")

    return parser


def setup_options(args):
    options = {
        'after_pull_request':
            Option(privileged=False,
                   value=False,  # not supported from command line
                   help="Wait for the given pull request id to be merged "
                        "before continuing with the current one"),
        'bypass_author_approval':
            Option(privileged=True,
                   value='bypass_author_approval' in args.cmd_line_options,
                   help="Bypass the pull request author's approval"),
        'bypass_build_status':
            Option(privileged=True,
                   value='bypass_build_status' in args.cmd_line_options,
                   help="Bypass the build and test status"),
        'bypass_commit_size':
            Option(privileged=True,
                   value='bypass_commit_size' in args.cmd_line_options,
                   help='Bypass the check on the size of the changeset '
                        '```TBA```'),
        'bypass_incompatible_branch':
            Option(privileged=True,
                   value='bypass_incompatible_branch' in args.cmd_line_options,
                   help="Bypass the check on the source branch prefix"),
        'bypass_jira_check':
            Option(privileged=True,
                   value='bypass_jira_check' in args.cmd_line_options,
                   help="Bypass the Jira issue check"),
        'bypass_peer_approval':
            Option(privileged=True,
                   value='bypass_peer_approval' in args.cmd_line_options,
                   help="Bypass the pull request peer's approval"),
        'bypass_tester_approval':
            Option(privileged=True,
                   value='bypass_tester_approval' in args.cmd_line_options,
                   help="Bypass the pull request tester's approval"),
        'unanimity':
            Option(privileged=False,
                   value='unanimity' in args.cmd_line_options,
                   help="Change review acceptance criteria from "
                        "`one reviewer at least` to `all reviewers` "),
        'wait':
            Option(privileged=False,
                   value='wait' in args.cmd_line_options,
                   help="Instruct Wall-E not to run until further notice")
    }
    return options


def setup_commands():
    commands = {
        'help':
            Command(privileged=False,
                    handler='print_help',
                    help='print Wall-E\'s manual in the pull-request'),
        'status':
            Command(privileged=False,
                    handler='publish_status_report',
                    help='print Wall-E\'s current status in '
                         'the pull-request ```TBA```'),
        'build':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='re-start a fresh build ```TBA```'),
        'retry':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='re-start a fresh build ```TBA```'),
        'clear':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='remove all comments from Wall-E from the '
                         'history ```TBA```'),
        'reset':
            Command(privileged=False,
                    handler='command_not_implemented',
                    help='delete integration branches, integration pull '
                         'requests, and restart merge process from the '
                         'beginning ```TBA```')
    }
    return commands


def main():
    parser = setup_parser()
    args = parser.parse_args()
    if not args.cmd_line_options:
        args.cmd_line_options = []

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    elif args.quiet:
        logging.basicConfig(level=logging.CRITICAL)
        # request lib is noisy
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.CRITICAL)
        requests_log.propagate = True
    else:
        logging.basicConfig(level=logging.INFO)
        # request lib is noisy
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.WARNING)
        requests_log.propagate = True

    if not args.settings:
        args.settings = args.slug

    if args.settings not in SETTINGS:
        print("Invalid repository/settings. I don't know how to work "
              "with %s. Specify settings with the --settings options." %
              args.settings)
        sys.exit(1)

    options = setup_options(args)
    commands = setup_commands()

    wall_e = WallE(WALL_E_USERNAME, args.password, WALL_E_EMAIL,
                   args.owner, args.slug, int(args.pull_request_id),
                   options, commands, SETTINGS[args.settings],
                   args.dry_run)

    is_repeat = "new"
    try:
        wall_e.handle_pull_request(
            reference_git_repo=args.reference_git_repo,
            no_comment=args.no_comment,
            interactive=args.interactive
        )

    except WallE_TemplateException as excp:
        try:
            wall_e.send_bitbucket_msg(unicode(excp),
                                      dont_repeat_if_in_history=excp.
                                      dont_repeat_if_in_history,
                                      no_comment=args.no_comment,
                                      interactive=args.interactive)
        except CommentAlreadyExists:
            is_repeat = "repeat"

        if args.backtrace:
            raise excp

        if not args.quiet:
            print('%d - %s (%s)' % (excp.code,
                                    excp.__class__.__name__,
                                    is_repeat))
        return excp.code, excp.__class__.__name__, is_repeat

    except (WallE_SilentException, WallE_DryRun) as excp:
        if args.backtrace:
            raise excp

        if not args.quiet:
            print('%d - %s (%s)' % (0,
                                    excp.__class__.__name__,
                                    is_repeat))
        return 0, excp.__class__.__name__, is_repeat

if __name__ == '__main__':
    main()
