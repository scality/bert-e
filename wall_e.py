#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
from collections import OrderedDict
import logging
import re
import smtplib
import sys
import time
import traceback

from jira.exceptions import JIRAError
import requests
import six

from template_loader import render
import bitbucket_api
from git_api import (Repository as GitRepository,
                     Branch,
                     MergeFailedException,
                     CheckoutFailedException)
from jira_api import JiraIssue
from wall_e_exceptions import (AuthorApprovalRequired,
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
                               HelpMessage,
                               ImproperEmailFormat,
                               IncompatibleSourceBranchPrefix,
                               IncorrectFixVersion,
                               IncorrectJiraProject,
                               IncorrectSourceBranchName,
                               InitMessage,
                               JiraIssueNotFound,
                               JiraUnknownIssueType,
                               MismatchPrefixIssueType,
                               MissingJiraId,
                               NothingToDo,
                               NotMyJob,
                               ParentPullRequestNotFound,
                               SubtaskIssueNotSupported,
                               PeerApprovalRequired,
                               StatusReport,
                               SuccessMessage,
                               TesterApprovalRequired,
                               UnableToSendEmail,
                               WallE_SilentException,
                               WallE_TemplateException)

if six.PY3:
    raw_input = input


WALL_E_USERNAME = 'scality_wall-e'
WALL_E_EMAIL = 'wall_e@scality.com'


SETTINGS = {
    'ring': {
        'jira_key': 'RING',
        'build_key': 'pipeline',
        'release_branch': {
            'prefix': 'release'
        },
        'stabilization_branch': {
            'prefix': 'stabilization',
            'versions': OrderedDict([('4.3.18', None)])
        },
        'development_branch': {
            'prefix': 'development',
            'versions': OrderedDict([
                ('4.3', {
                    'upcoming_release': '4.3.18',
                    'allow_ticketless': False,
                    'allow_prefix': [
                        'bugfix',
                        'improvement'
                    ]
                }),
                ('5.1', {
                    'upcoming_release': '5.1.5',
                    'allow_ticketless': False,
                    'allow_prefix': [
                        'bugfix',
                        'improvement'
                    ]
                }),
                ('6.0', {
                    'upcoming_release': '6.0.0',
                    'allow_ticketless': True,
                    'allow_prefix': [
                        'bugfix',
                        'improvement',
                        'feature',
                        'project'
                    ]
                })
            ]),
        },
        'integration_branch': {
            'prefix': 'w',
        },
        'feature_branch': {
            'prefix': [
                'feature',
                'bugfix',
                'improvement',
                'project'
            ],
            'ignore_prefix': [
                'hotfix',
                'user'
            ]
        },
        'testers': [
            WALL_E_USERNAME,   # we need this for test purposes
            'anneharper',
            'christophe_meron',
            'christophe_stoyanov',
            'lpantou',
            'mcolzi',
            'romain_thebaud',
            'sleibo'
        ],
        'admins': [
            WALL_E_USERNAME,   # we need this for test purposes
            'anneharper',
            'bertrand_demiddelaer_scality',
            'ludovicmaillard',
            'mcolzi',
            'mouhamet7',
            'mvaude',
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
        ]
    },
    'wall-e': {
        'jira_key': 'RELENG',
        'build_key': 'autotest',
        'release_branch': {
            'prefix': 'release'
        },
        'stabilization_branch': {
            'prefix': 'stabilization'
        },
        'development_branch': {
            'prefix': 'development',
            'versions': OrderedDict([
                ('1.0', {
                    'upcoming_release': '1.0.0',
                    'allow_ticketless': False,
                    'allow_prefix': [
                        'bugfix',
                        'improvement',
                        'feature',
                        'project'
                    ]
                })
            ]),
        },
        'integration_branch': {
            'prefix': 'w',
        },
        'feature_branch': {
            'prefix': [
                'feature',
                'bugfix',
                'improvement',
                'project'
            ],
            'ignore_prefix': [
                'hotfix',
                'user'
            ]
        },
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
        'build_key': 'autotest',
        'release_branch': {
            'prefix': 'release'
        },
        'stabilization_branch': {
            'prefix': 'stabilization'
        },
        'development_branch': {
            'prefix': 'development',
            'versions': OrderedDict([
                ('1.0', {
                    'upcoming_release': '1.0.0',
                    'allow_ticketless': False,
                    'allow_prefix': [
                        'bugfix',
                        'improvement',
                        'feature',
                        'project'
                    ]
                })
            ]),
        },
        'integration_branch': {
            'prefix': 'w',
        },
        'feature_branch': {
            'prefix': [
                'feature',
                'bugfix',
                'improvement',
                'project'
            ],
            'ignore_prefix': [
                'hotfix',
                'user'
            ]
        },
        'testers': [
        ],
        'admins': [
            'pierre_louis_bonicoli',
            'rayene_benrayana',
            'sylvain_killian'
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


def setup_email(destination):
    """Check the capacity to send emails."""
    match_ = re.match("(?P<short_name>[^@]*)@.*", destination)
    if not match_:
        raise ImproperEmailFormat("The specified email does "
                                  "not seem valid (%s)" % destination)
    try:
        smtplib.SMTP('localhost')
    except Exception as excp:
        raise UnableToSendEmail("Unable to send email (%s)" % excp)


def send_email(destination, title, content):
    """Send some data by email."""
    match_ = re.match("(?P<short_name>[^@]*)@.*", destination)
    if not match_:
        raise ImproperEmailFormat("The specified email does "
                                  "not seem valid (%s)" % destination)
    body = render('email_alert.md',
                  name=match_.group('short_name'),
                  subject=title,
                  content=content,
                  destination=destination,
                  email=WALL_E_EMAIL)
    smtpObj = smtplib.SMTP('localhost')
    smtpObj.sendmail(WALL_E_EMAIL, [destination], body)


def confirm(question):
    input_ = raw_input(question + " Enter (y)es or (n)o: ")
    return input_ == "yes" or input_ == "y"


class BranchName(Branch):
    pattern = '(?P<prefix>[a-b]+)/(?P<label>.*)'
    cascade_producer = False
    cascade_consumer = False
    can_be_destination = False

    def __init__(self, repo, name, settings=None):
        Branch.__init__(self, repo, name)
        #self.name = name
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

class HotfixBranch(BranchName):
    pattern = 'hotfix/(?P<label>.*)'



class DevelopmentBranch(BranchName):
    pattern = 'development/(?P<version>(?P<major>\d+)\.(?P<minor>\d+))'
    micro = None
    cascade_producer = True
    cascade_consumer = True
    can_be_destination = True

    def __eq__(self, other):
        return self.__class__ == other.__class__ and \
               self.major == other.major and \
               self.minor == other.minor


class StabilizationBranch(DevelopmentBranch):
    pattern = 'stabilization/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+))'
    cascade_producer = True
    can_be_destination = True

    def __eq__(self, other):
        return DevelopmentBranch.__eq__(self, other) and \
            self.micro == other.micro


class ReleaseBranch(BranchName):
    pattern = 'release/(?P<version>(?P<major>\d+)\.(?P<minor>\d+))'

class FeatureBranch(BranchName):
    jira_issue_pattern = '(?P<jira_issue_key>(?P<jira_project>[A-Z0-9_]+)-[0-9]+)'
    prefixes = '(?P<prefix>(feature|improvement|bugfix|project))'
    pattern = "%s/(%s(?P<label>.*)|.+)" % (prefixes, jira_issue_pattern)
    cascade_producer = True

class IntegrationBranch(BranchName):
    pattern = 'w/(?P<version>(?P<major>\d+)\.(?P<minor>\d+)(\.(?P<micro>\d+))?)/' + FeatureBranch.pattern

    def merge_from_branch(self, source_branch):
        try:
            self.merge(source_branch, do_push=True)
        except MergeFailedException:
            raise Conflict(source=source_branch,
                           destination=self)

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

    def get_or_create_pull_request(self, parent_pr, open_prs, bitbucket_repo):
        title = 'INTEGRATION [PR#%s > %s] %s' % (
            parent_pr['id'],
            self.destination_branch.name,
            parent_pr['title']
        )

        # WARNING potential infinite loop:
        # creating a child pr will trigger a 'pr update' webhook
        # wall-e will analyse it, retrieve the main pr, then
        # re-enter here and recreate the children pr.
        # solution: do not create the pr if it already exists
        pr = self._get_pull_request_from_list(open_prs)
        if not pr:
            description = render('pull_request_description.md',
                                 wall_e=WALL_E_USERNAME,
                                 pr=parent_pr)
            pr = bitbucket_repo.create_pull_request(
                title=title,
                name='name',
                source={'branch': {'name': self.name}},
                destination={'branch': {'name': self.destination_branch.name}},
                close_source_branch=True,
                reviewers=[{'username': parent_pr['author']['username']}],
                description=description)
        return pr


class UnrecognizedBranchPattern(Exception):
    pass


class StabilizationBranchWithoutDevBranch(Exception):
    pass


class VersionMismatch(Exception):
    pass


class NoMicroVersionForDevelopmentBranch(Exception):
    pass



def branch_factory(repo, branch_name):
    for cls in [StabilizationBranch, DevelopmentBranch, ReleaseBranch,
                FeatureBranch, HotfixBranch, IntegrationBranch]:
        try:
            branch = cls(repo, branch_name)
            return branch
        except BranchNameInvalid:
            pass

    raise UnrecognizedBranchPattern(branch_name)

class BranchCascade(object):
    def __init__(self):
        self._cascade = OrderedDict()
        self._is_valid = False

    def add_branch(self, branch):
        if not branch.can_be_destination:
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
        self._cascade[(major, minor)][branch.__class__] = max(cur_branch, branch)

    def validate(self):
        previous_dev_branch = None
        for (major, minor), branch_set in self._cascade.items():
            dev_branch = branch_set[DevelopmentBranch]
            if dev_branch is None:
                raise DevBranchDoesNotExist("associated to %s" % stb_branch)

            stb_branch = branch_set[StabilizationBranch]

            if dev_branch.micro is None:
                if stb_branch is None:
                    raise NoMicroVersionForDevelopmentBranch(dev_branch)
                dev_branch.micro = int(stb_branch.micro) + 1

            elif dev_branch.micro - int(stb_branch.micro) != 1:
                raise VersionMismatch(stb_branch, dev_branch)


            if stb_branch:
                if not dev_branch.includes_commit(stb_branch):
                    raise DevBranchesNotSelfContained(stb_branch, dev_branch)

            if previous_dev_branch:
                if not dev_branch.includes_commit(previous_dev_branch):
                    raise DevBranchesNotSelfContained(previous_dev_branch, dev_branch)



            previous_dev_branch = dev_branch
        self._is_valid = True

    def adapt_cascade_to_destination_branch(self, destination_branch):
        assert self._is_valid
        for (major, minor), branch_set in self._cascade.items():
            if destination_branch == branch_set[StabilizationBranch]:
                return
            branch_set[StabilizationBranch] = None
            if destination_branch == branch_set[DevelopmentBranch]:
                return
            branch_set[DevelopmentBranch] = None
            del self._cascade[(major, minor)]
        # We should never reach this point
        raise Exception("The destination branch was not found in cascade")

    def destination_branches(self, destination_branch):
        assert self._is_valid
        destination_branches = []
        include_next_development_branches = False
        for (major, minor), branch_set in self._cascade.items():
            if branch_set[StabilizationBranch] == destination_branch:
                destination_branches.append(branch_set[StabilizationBranch])
                include_next_development_branches = True
            if branch_set[DevelopmentBranch] == destination_branch:
                include_next_development_branches = True
            if include_next_development_branches:
                destination_branches.append(branch_set[DevelopmentBranch])
        return destination_branches

    def _create_integration_branches(self, repo, source_branch, destination_branch):
        integration_branches = []
        for destination_branch in self.destination_branches(destination_branch):
            name = 'w/%s/%s' % (destination_branch.version, source_branch)
            integration_branch = IntegrationBranch(repo, name)
            integration_branch.destination_branch = destination_branch
            integration_branch.source_branch = source_branch
            integration_branches.append(integration_branch)
            if not integration_branch.exists():
                integration_branch.create(
                    integration_branch.destination_branch)
        return integration_branches






class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail,
                 owner, slug, pull_request_id, options, commands, settings):
        self._bbconn = bitbucket_api.Client(
            bitbucket_login, bitbucket_password, bitbucket_mail)
        self.bbrepo = bitbucket_api.Repository(
            self._bbconn, owner=owner, repo_slug=slug)
        self.main_pr = self.bbrepo.get_pull_request(
            pull_request_id=pull_request_id)
        self.author = self.main_pr['author']['username']
        if WALL_E_USERNAME == self.author:
            res = re.search('(?P<pr_id>\d+)',
                            self.main_pr['description'])
            if not res:
                raise ParentPullRequestNotFound('Not found')
            self.pull_request_id = res.group('pr_id')
            self.main_pr = self.bbrepo.get_pull_request(
                pull_request_id=int(res.group())
            )
            self.author = self.main_pr['author']['username']
        self.options = options
        self.commands = commands
        self.settings = settings
        self.source_branch = None
        self.destination_branches = []
        #self.target_versions = {}
        self._cascade = BranchCascade()

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
        # the last comment posted is the first in the list
        for index, comment in enumerate(self.main_pr.get_comments()):
            u = comment['user']['username']
            raw = comment['content']['raw']
            # python3
            if isinstance(username, str) and u != username:
                continue
            # python2
            if isinstance(username, list) and u not in username:
                continue
            if startswith and not raw.startswith(startswith):
                continue
            if max_history and index > max_history:
                return
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

        self.main_pr.add_comment(msg)

    def _check_pr_state(self):
        if self.main_pr['state'] != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDo('The pull-request\'s state is "%s"'
                              % self.main_pr['state'])

    def _check_if_ignored(self, src_branch_name, dst_branch_name):
        # check feature branch
        if not src_branch_name.cascade_producer:
            raise NotMyJob(src_branch_name, dst_branch_name)

        # check selected destination branch
        if not dst_branch_name.cascade_consumer:
            raise NotMyJob(src_branch_name, dst_branch_name)

    def _send_greetings(self, comments):
        """Displays a welcome message if conditions are met."""
        for comment in comments:
            author = comment['user']['username']
            if isinstance(author, list):
                # python2 returns a list
                if len(author) != 1:
                    continue
                author = author[0]

            if author == WALL_E_USERNAME:
                return

        raise InitMessage(author=self.author,
                          status=self.get_status_report(),
                          active_options=self._get_active_options())

    def _check_options(self, comment_author, pr_author, keyword_list):
        logging.debug('checking keywords %s', keyword_list)

        for keyword in keyword_list:
            if keyword not in self.options.keys():
                logging.debug('ignoring keywords in this comment due to '
                              'an unknown keyword `%s`', keyword_list)
                return False

            limited_access = self.options[keyword].privileged
            if limited_access:
                if comment_author == pr_author:
                    logging.debug('cannot use privileges on own PR')
                    return False

                if comment_author not in self.settings['admins']:
                    logging.debug('ignoring keywords in this comment due to '
                                  'unsufficient credentials `%s`',
                                  keyword_list)
                    return False

        return True

    def _get_options(self, comments, pr_author):
        """Load settings from pull-request comments."""
        for comment in comments:
            raw = comment['content']['raw']
            if not raw.strip().startswith('@%s' % WALL_E_USERNAME):
                continue

            logging.debug('Found a keyword comment: %s', raw)
            raw_cleaned = raw.strip()[len(WALL_E_USERNAME)+1:]

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
            regexp = r"\s*(?P<keywords>(\s+\w+)+)\s*$"
            match_ = re.match(regexp, raw_cleaned)
            if not match_:
                logging.debug('Keyword comment ignored. '
                              'Not an option, unknown format: %s', raw)
                continue

            keywords = match_.group('keywords').strip().split()

            if not self._check_options(author, pr_author, keywords):
                logging.debug('Keyword comment ignored. '
                              'Not an option, checks failed: %s', raw)
                continue

            for keyword in keywords:
                self.options[keyword].set(True)

    def _check_command(self, author, command):
        logging.debug('checking command %s', command)

        if command not in self.commands.keys():
            logging.debug('ignoring command in this comment due to '
                          'an unknown command `%s`', command)
            return False

        limited_access = self.commands[command].privileged
        if limited_access and author not in self.settings['admins']:
            logging.debug('ignoring command in this comment due to '
                          'unsufficient credentials `%s`', command)
            return False

        return True

    def _handle_commands(self, comments):
        """Detect the last command in pull-request comments and act on it."""
        for comment in comments:
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

            if not self._check_command(author, command):
                logging.debug('Command comment ignored. '
                              'Not a command, checks failed: %s' % raw)
                continue

            # get command handler and execute it
            assert hasattr(self, self.commands[command].handler)
            handler = getattr(self, self.commands[command].handler)
            handler(match_.group('args'))

    def _setup_source_branch(self, repo, src_branch_name, dst_branch_name):
        try:
            self.source_branch = branch_factory(repo, self.main_pr['source']['branch']['name'])
        except UnrecognizedBranchPattern:
            raise IncorrectSourceBranchName(
                source=self.main_pr['source']['branch']['name'],
                destination=self.main_pr['destination']['branch']['name'],
                valid_prefixes=self.settings['feature_branch']['prefix'])


    def _setup_destination_branch(self, repo, src_branch_name, dst_branch_name):
        self.destination_branch = branch_factory(repo, self.main_pr['destination']['branch']['name'])

    def _check_compatibility_src_dest(self):
        if self.source_branch.prefix == 'feature' and \
            self.destination_branch != self._cascade.destination_branches(self.destination_branch)[-1]:
            raise IncompatibleSourceBranchPrefix(
                    source=self.source_branch,
                    destination=self.destination_branch)



    def _jira_check_reference(self):
        if self.source_branch.jira_issue_key:
            return

        for destination_branch in self.destination_branches:
            if not destination_branch.allow_ticketless:
                raise MissingJiraId(source_branch=self.source_branch.name,
                                    dest_branch=destination_branch.name)

    def _jira_get_issue(self, issue_id):
        try:
            issue = JiraIssue(issue_id=issue_id, login='wall_e',
                              passwd=self._bbconn.auth.password)
        except JIRAError as e:
            if e.status_code == 404:
                raise JiraIssueNotFound(issue=issue_id)
            else:
                raise

        return issue

    def _jira_check_project(self, issue):
        # check the project
        if (self.source_branch.jira_project !=
                self.settings['jira_key']):
            raise IncorrectJiraProject(
                expected_project=self.settings['jira_key'],
                issue=issue
            )

    def _jira_check_issue_type(self, issue):
        issuetype = issue.fields.issuetype.name

        if issuetype == 'Sub-task':
            raise SubtaskIssueNotSupported(issue=issue,
                                           pairs=JIRA_ISSUE_BRANCH_PREFIX)

        expected_prefix = JIRA_ISSUE_BRANCH_PREFIX.get(issuetype)
        if expected_prefix is None:
            raise JiraUnknownIssueType(issuetype)

        if expected_prefix != self.source_branch.prefix:
            raise MismatchPrefixIssueType(prefix=self.source_branch.prefix,
                                          expected=expected_prefix,
                                          pairs=JIRA_ISSUE_BRANCH_PREFIX,
                                          issue=issue)

    def _jira_check_version(self, issue):
        issue_versions = set([version.name for version in
                              issue.fields.fixVersions])
        expect_versions = set(
            self.target_versions.values())

        if issue_versions != expect_versions:
            raise IncorrectFixVersion(issue=issue,
                                      issue_versions=issue_versions,
                                      expect_versions=expect_versions)

    def _jira_checks(self):
        """Check the Jira issue id specified in the source branch."""
        if self.option_is_set('bypass_jira_check'):
            return

        if not self.settings['jira_key']:
            return

        self._jira_check_reference()

        issue_id = self.source_branch.jira_issue_key
        issue = self._jira_get_issue(issue_id)

        self._jira_check_project(issue)
        self._jira_check_issue_type(issue)
        self._jira_check_version(issue)

    def _clone_git_repo(self, reference_git_repo):
        git_repo = GitRepository(self.bbrepo.get_git_url())
        git_repo.clone(reference_git_repo)
        git_repo.get_all_branches_locally()
        git_repo.config('user.email', WALL_E_EMAIL)
        git_repo.config('user.name', WALL_E_USERNAME)
        return git_repo

    def _check_source_branch_still_exists(self, git_repo):
        # check source branch still exists
        # (it may have been deleted by developers)
        try:
            Branch(git_repo, self.source_branch.name).checkout()
        except CheckoutFailedException:
            raise NothingToDo(self.source_branch.name)

    def _check_git_repo_health(self, git_repo):
        # check target branches
        previous_dev_branch_name = '%s/%s' % (
            self.settings['development_branch']['prefix'],
            list(self.settings['development_branch']['versions'])[0]
        )
        #try:
        #    Branch(git_repo, previous_dev_branch_name).checkout()
        #except CheckoutFailedException:
        #    raise DevBranchDoesNotExist(previous_dev_branch_name)

        for version in list(
                self.settings['development_branch']['versions'])[1:]:
            dev_branch_name = '%s/%s' % (
                self.settings['development_branch']['prefix'],
                version
            )
            dev_branch = Branch(git_repo, dev_branch_name)
            try:
                dev_branch.checkout()
            except CheckoutFailedException:
                raise DevBranchDoesNotExist(dev_branch_name)
            if not dev_branch.includes_commit(previous_dev_branch_name):
                raise DevBranchesNotSelfContained(previous_dev_branch_name,
                                                  dev_branch_name)
            previous_dev_branch_name = dev_branch_name

    def _build_branch_cascade(self, git_repo):

        #for tag in git_repo.cmd('git tag').split('\n')[:-1]:
        #    self._cascade.add_tag(tag)
        for branch in git_repo.cmd('git branch').split('\n')[:-1]:
            try:
                branch = branch_factory(git_repo, branch[2:])
            except UnrecognizedBranchPattern(branch[2:]):
                continue
            self._cascade.add_branch(branch)



    def _check_history_did_not_change(self, integration_branch):
        development_branch = integration_branch.destination_branch
        for commit in integration_branch.get_all_commits(integration_branch.source_branch):
            if not development_branch.includes_commit(commit):
                raise BranchHistoryMismatch(
                    commit=commit,
                    integration_branch=integration_branch,
                    feature_branch=integration_branch.source_branch,
                    development_branch=development_branch
                )

    def _update_integration_from_dev(self, integration_branches):
        # The first integration branch should not contain commits
        # that are not in development/* or in the feature branch.
        self._check_history_did_not_change(integration_branches[0])
        for integration_branch in integration_branches:
            integration_branch.merge_from_branch(
                integration_branch.destination_branch)

    def _update_integration_from_feature(self, integration_branches):
        branch_to_merge_from = self.source_branch
        for integration_branch in integration_branches:
            integration_branch.merge_from_branch(branch_to_merge_from)
            branch_to_merge_from = integration_branch

    def _create_pull_requests(self, integration_branches):
        # read open PRs and store them for multiple usage
        open_prs = list(self.bbrepo.get_pull_requests())
        return [integration_branch.
                get_or_create_pull_request(
                    self.main_pr,
                    open_prs,
                    self.bbrepo) for
                integration_branch in integration_branches]

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

        if not self.settings['testers']:
            # if the project does not declare any testers,
            # just assume a pseudo-tester has approved the PR
            approved_by_tester = True

        #  If a tester is the author of the PR we will bypass
        #  the tester approval
        if self.author in self.settings['testers']:
            approved_by_tester = True

        if approved_by_author and approved_by_peer and approved_by_tester:
            return

        # NB: when author hasn't approved the PR, author isn't listed in
        # 'participants'
        for participant in self.main_pr['participants']:
            if not participant['approved']:
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
                child_prs=child_prs,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
            )

        if not approved_by_peer:
            raise PeerApprovalRequired(
                pr=self.main_pr,
                child_prs=child_prs,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
            )

        if not approved_by_tester:
            raise TesterApprovalRequired(
                pr=self.main_pr,
                child_prs=child_prs,
                author_approval=approved_by_author,
                peer_approval=approved_by_peer,
                tester_approval=approved_by_tester,
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
            raise BuildFailed(pr_id=worst_pr['id'])
        elif g_state == 'NOTSTARTED':
            raise BuildNotStarted()
        elif g_state == 'INPROGRESS':
            raise BuildInProgress()
        assert build_state == 'SUCCESSFUL'

    def handle_pull_request(self, reference_git_repo='',
                            no_comment=False, interactive=False):

        self._check_pr_state()



        repo = self._clone_git_repo(reference_git_repo)
        src_branch_name = self.main_pr['source']['branch']['name']
        dst_branch_name = self.main_pr['destination']['branch']['name']
        self._setup_source_branch(repo, src_branch_name, dst_branch_name)
        self._setup_destination_branch(repo, src_branch_name, dst_branch_name)




        self._check_if_ignored(self.source_branch, self.destination_branch)
        self._build_branch_cascade(repo)
        self._cascade.validate()
        self._cascade.adapt_cascade_to_destination_branch(self.destination_branch)



        # read comments and store them for multiple usage
        comments = list(self.main_pr.get_comments())

        #self._send_greetings(comments)
        self._get_options(comments, self.author)
        self._handle_commands(comments)

        if self.option_is_set('wait'):
            raise NothingToDo('wait option is set')

        self._check_compatibility_src_dest()
        self._jira_checks()


        # self._check_git_repo_health(repo)
        self._check_source_branch_still_exists(repo)
        integration_branches = self._cascade._create_integration_branches(repo, self.source_branch, self.destination_branch)
        self._update_integration_from_dev(integration_branches)
        self._update_integration_from_feature(integration_branches)
        child_prs = self._create_pull_requests(integration_branches)
        self._check_approvals(child_prs)
        self._check_build_status(child_prs)

        if interactive and not confirm('Do you want to merge ?'):
            return

        for integration_branch in integration_branches:
            integration_branch.update_to_development_branch()

        self._check_git_repo_health(repo)
        #repo.delete()

        raise SuccessMessage(branches=self.destination_branches,
                             issue=self.source_branch.jira_issue_key,
                             author=self.author)


def setup_parser():
    parser = argparse.ArgumentParser(add_help=False,
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
        '--alert-email', action='store', default=None, type=str,
        help="Where to send notifications in case of "
             "incorrect behaviour")
    parser.add_argument(
        '--backtrace', action='store_true', default=False,
        help="Show backtrace instead of return code on console")
    parser.add_argument(
        '--quiet', action='store_true', default=False,
        help="Don't print return codes on the console")

    return parser


def setup_options(args):
    options = {
        'bypass_peer_approval':
            Option(privileged=True,
                   value='bypass_peer_approval' in args.cmd_line_options,
                   help="Bypass the pull request author's approval"),
        'bypass_author_approval':
            Option(privileged=True,
                   value='bypass_author_approval' in args.cmd_line_options,
                   help="Bypass the pull request peer's approval"),
        'bypass_tester_approval':
            Option(privileged=True,
                   value='bypass_tester_approval' in args.cmd_line_options,
                   help="Bypass the pull request tester's approval"),
        'bypass_jira_check':
            Option(privileged=True,
                   value='bypass_jira_check' in args.cmd_line_options,
                   help="Bypass the Jira issue check"),
        'bypass_build_status':
            Option(privileged=True,
                   value='bypass_build_status' in args.cmd_line_options,
                   help="Bypass the build and test status"),
        'bypass_commit_size':
            Option(privileged=True,
                   value='bypass_commit_size' in args.cmd_line_options,
                   help='Bypass the check on the size of the changeset '
                        '```TBA```'),
        'unanimity':
            Option(privileged=False,
                   value='unanimity' in args.cmd_line_options,
                   help="Change review acceptance criteria from "
                        "`one reviewer at least` to `all reviewers` "
                        "```TBA```"),
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

    if args.alert_email:
        try:
            setup_email(args.alert_email)
        except ImproperEmailFormat:
            print("Invalid email (%s)" % args.alert_email)
            sys.exit(1)
        except UnableToSendEmail:
            print("It appears I won't be able to send emails, please check "
                  "the email server.")
            sys.exit(1)

    options = setup_options(args)
    commands = setup_commands()

    wall_e = WallE(WALL_E_USERNAME, args.password, WALL_E_EMAIL,
                   args.owner, args.slug, int(args.pull_request_id),
                   options, commands, SETTINGS[args.settings])

    try:
        wall_e.handle_pull_request(
            reference_git_repo=args.reference_git_repo,
            no_comment=args.no_comment,
            interactive=args.interactive
        )

    except WallE_TemplateException as excp:
        try:
            wall_e.send_bitbucket_msg(str(excp),
                                      dont_repeat_if_in_history=excp.
                                      dont_repeat_if_in_history,
                                      no_comment=args.no_comment,
                                      interactive=args.interactive)
        except CommentAlreadyExists:
            logging.info('Comment already posted.')

        if args.backtrace:
            raise excp

        if not args.quiet:
            print('%d - %s' % (excp.code, excp.__class__.__name__))
        return excp.code

    except WallE_SilentException as excp:
        if args.backtrace:
            raise excp

        if not args.quiet:
            print('%d - %s' % (0, excp.__class__.__name__))
        return 0

    except Exception:
        if args.alert_email:
            send_email(destination=args.alert_email,
                       title="[Wall-E] Unexpected termination "
                             "(%s)" % time.asctime(),
                       content=traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
