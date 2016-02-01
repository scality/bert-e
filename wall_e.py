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
from bitbucket_api import (Repository as BitBucketRepository,
                           Client)
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
                               ParentJiraIssueNotFound,
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
                    'upcoming_release': '5.1.4',
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
                        'project']
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

    An option may require priviledges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, priviledged, help, value=False):
        self.value = value
        self.help = help
        self.priviledged = priviledged

    def set(self, value):
        self.value = value

    def is_set(self):
        return self.value


class Command(object):
    """Wall-E commands implementation.

    Wall-E uses commands to operate one-time actions.

    Commands are triggered by adding a comment in the
    pull-request.

    A command may require priviledges, in which case only
    members of admin will be able to activate
    it.

    """
    def __init__(self, priviledged, help, handler):
        self.handler = handler
        self.help = help
        self.priviledged = priviledged


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


class BranchName(object):
    def __init__(self, name):
        self.name = name
        if '/' not in name:
            raise BranchNameInvalid(name)


class FeatureBranch(BranchName):
    def __init__(self, name, valid_prefixes):
        super(FeatureBranch, self).__init__(name)
        self.prefix, self.subname = name.split('/', 1)

        if not self.prefix or not self.subname:
            raise BranchNameInvalid(name)

        if self.prefix not in valid_prefixes:
            raise BranchNameInvalid(name)

        match = re.match('(?P<issue_id>(?P<key>[A-Z]+)-\d+).*',
                         self.subname)
        if match:
            self.jira_issue_id = match.group('issue_id')
            self.jira_project_key = match.group('key')
        else:
            logging.warning('%s does not contain a correct '
                            'issue id number', self.name)
            self.jira_issue_id = None
            self.jira_project_key = None


class DestinationBranch(BranchName):
    def __init__(self, name, settings):
        super(DestinationBranch, self).__init__(name)
        self.prefix, self.version = name.split('/', 1)
        self.upcoming_release = settings['upcoming_release']
        self.allow_ticketless = settings['allow_ticketless']
        self.allow_prefix = settings['allow_prefix']


class IntegrationBranch(Branch):
    def __init__(self, repo, name, dev_branch_name):
        Branch.__init__(self, repo, name)
        w, self.version, self.subname = name.split('/', 2)
        self.development_branch = Branch(
            repo=repo,
            name=dev_branch_name
        )

    def merge_from_branch(self, source_branch):
        try:
            self.merge(source_branch, do_push=True)
        except MergeFailedException:
            raise Conflict(source=source_branch,
                           destination=self)

    def update_to_development_branch(self):
        self.development_branch.merge(self, force_commit=False)
        self.development_branch.push()

    def create_pull_request(self, parent_pr, bitbucket_repo):
        title = '[%s] #%s: %s' % (self.development_branch.name,
                                  parent_pr['id'], parent_pr['title'])

        description = render('pull_request_description.md',
                             wall_e=WALL_E_USERNAME,
                             pr=parent_pr)
        pr = bitbucket_repo.create_pull_request(
            title=title,
            name='name',
            source={'branch': {'name': self.name}},
            destination={'branch': {'name': self.development_branch.name}},
            close_source_branch=True,
            reviewers=[{'username': parent_pr['author']['username']}],
            description=description)
        return pr


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail,
                 owner, slug, pull_request_id, options, commands, settings):
        self._bbconn = Client(bitbucket_login,
                              bitbucket_password, bitbucket_mail)
        self.bbrepo = BitBucketRepository(self._bbconn, owner=owner,
                                          repo_slug=slug)
        self.main_pr = self.bbrepo.get_pull_request(
            pull_request_id=pull_request_id
        )
        self.author = self.main_pr['author']['username']
        if WALL_E_USERNAME == self.author:
            res = re.search('(?P<pr_id>\d+)',
                            self.main_pr['description'])
            if not res:
                raise ParentPullRequestNotFound('Not found')
            self.pull_request_id = res.group('pr_id')
            self.main_pr = self.bbrepo.get_pull_request(
                pull_request_id=res.group()
            )
            self.author = self.main_pr['author']['username']
        self.options = options
        self.commands = commands
        self.settings = settings
        self.source_branch = None
        self.destination_branches = []
        self.target_versions = {}

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
            if self.find_bitbucket_comment(username=WALL_E_USERNAME,
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
        # check selected destination branch
        dev_branch_settings = self.settings['development_branch']
        prefix = dev_branch_settings['prefix']
        match_ = re.match("%s/(?P<version>.*)" % prefix, dst_branch_name)
        if not match_:
            raise NotMyJob(src_branch_name, dst_branch_name)

        if match_.group('version') not in dev_branch_settings['versions']:
            raise NotMyJob(src_branch_name, dst_branch_name)

        # check feature branch
        for prefix in self.settings['feature_branch']['ignore_prefix']:
            if src_branch_name.startswith(prefix):
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

    def _check_options(self, author, keyword_list):
        logging.debug('checking keywords %s', keyword_list)

        for keyword in keyword_list:
            if keyword not in self.options.keys():
                logging.debug('ignoring keywords in this comment due to '
                              'an unknown keyword `%s`', keyword_list)
                return False

            limited_access = self.options[keyword].priviledged
            if limited_access and author not in self.settings['admins']:
                logging.debug('ignoring keywords in this comment due to '
                              'unsufficient credentials `%s`', keyword_list)
                return False

        return True

    def _get_options(self, comments):
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
                logging.warning('Keyword comment ignored. '
                                'Unknown format: %s', raw)
                continue

            keywords = match_.group('keywords').strip().split()

            if not self._check_options(author, keywords):
                logging.debug('Keyword comment ignored. '
                              'Checks failed: %s', raw)
                continue

            for keyword in keywords:
                self.options[keyword].set(True)

    def _check_command(self, author, command):
        logging.debug('checking command %s', command)

        if command not in self.commands.keys():
            logging.debug('ignoring command in this comment due to '
                          'an unknown command `%s`', command)
            return False

        limited_access = self.commands[command].priviledged
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
                                'Unknown format: %s' % raw)
                continue

            command = match_.group('command')

            if not self._check_command(author, command):
                logging.warning('Command comment ignored. '
                                'Checks failed: %s' % raw)
                continue

            # get command handler and execute it
            assert hasattr(self, self.commands[command].handler)
            handler = getattr(self, self.commands[command].handler)
            handler(match_.group('args'))

    def _build_target_versions(self, dst_branch_name):
        match_ = re.match("[^/]*/(?P<minver>.*)", dst_branch_name)
        assert match_  # should work, already tested
        # target versions are all versions above `minver`
        self.target_versions = OrderedDict(
            [(version, data['upcoming_release']) for (version, data) in
                self.settings['development_branch']['versions'].items()
                if version >= match_.group('minver')])

    def _setup_source_branch(self, src_branch_name, dst_branch_name):
        try:
            self.source_branch = FeatureBranch(
                src_branch_name,
                self.settings['feature_branch']['prefix']
            )
        except BranchNameInvalid:
            raise IncorrectSourceBranchName(
                source=src_branch_name,
                destination=dst_branch_name,
                valid_prefixes=self.settings['feature_branch']['prefix']
            )

    def _setup_destination_branches(self, src_branch_name, dst_branch_name):
        for version in self.target_versions:
            branch_name = "%s/%s" % (
                self.settings['development_branch']['prefix'],
                version
            )
            destination_branch = DestinationBranch(
                branch_name,
                self.settings['development_branch']['versions'][version]
            )
            self.destination_branches.append(destination_branch)

    def _check_compatibility_src_dest(self):
        for destination_branch in self.destination_branches:
            if (self.source_branch.prefix not in
                    destination_branch.allow_prefix):
                raise IncompatibleSourceBranchPrefix(
                    source=self.source_branch,
                    destination=destination_branch)

    def _jira_check_reference(self):
        if self.source_branch.jira_issue_id:
            return

        for destination_branch in self.destination_branches:
            if not destination_branch.allow_ticketless:
                raise MissingJiraId(branch=self.source_branch.name)

    def _jira_get_issue(self, issue_id):
        try:
            issue = JiraIssue(issue_id=issue_id, login='wall_e',
                              passwd=self._bbconn.auth.password)
        except JIRAError as e:
            if e.status_code == 404:
                raise JiraIssueNotFound(issue=issue_id)
            else:
                raise

        # Use parent task if subtask
        if issue.fields.issuetype.name == 'Sub-task':
            try:
                parent_id = issue.fields.parent.key
                issue = JiraIssue(issue_id=parent_id, login='wall_e',
                                  passwd=self._bbconn.auth.password)
            except JIRAError as e:
                if e.status_code == 404:
                    raise ParentJiraIssueNotFound(parent=parent_id,
                                                  issue=issue_id)
                else:
                    raise

        return issue

    def _jira_check_project(self, issue_id, issue):
        # check the project
        if (self.source_branch.jira_project_key !=
                self.settings['jira_key']):
            raise IncorrectJiraProject(
                expected_project=self.settings['jira_key'],
                issue=issue_id
            )

    def _jira_check_issue_type(self, issue):
        issuetype = issue.fields.issuetype.name
        expected_prefix = JIRA_ISSUE_BRANCH_PREFIX.get(issuetype)
        if expected_prefix is None:
            raise JiraUnknownIssueType(issuetype)
        if expected_prefix != self.source_branch.prefix:
            raise MismatchPrefixIssueType(prefix=self.source_branch.prefix,
                                          expected=expected_prefix)

    def _jira_check_version(self, issue):
        issue_versions = set([version.name for version in
                              issue.fields.fixVersions])
        expect_versions = set(
            self.target_versions.values())

        if issue_versions != expect_versions:
            raise IncorrectFixVersion(issues=issue_versions,
                                      expects=expect_versions)

    def _jira_checks(self):
        """Check the Jira issue id specified in the source branch."""
        if self.option_is_set('bypass_jira_check'):
            return

        if not self.settings['jira_key']:
            return

        self._jira_check_reference()

        issue_id = self.source_branch.jira_issue_id
        issue = self._jira_get_issue(issue_id)

        self._jira_check_project(issue_id, issue)
        self._jira_check_issue_type(issue)
        self._jira_check_version(issue)

    def _clone_git_repo(self, reference_git_repo):
        git_repo = GitRepository(self.bbrepo.get_git_url())
        git_repo.clone(reference_git_repo)
        git_repo.config('user.email', WALL_E_EMAIL)
        git_repo.config('user.name', WALL_E_USERNAME)
        return git_repo

    def _check_git_repo_health(self, git_repo):
        previous_dev_branch_name = '%s/%s' % (
            self.settings['development_branch']['prefix'],
            list(self.settings['development_branch']['versions'])[0]
        )
        try:
            Branch(git_repo, previous_dev_branch_name).checkout()
        except CheckoutFailedException:
            raise DevBranchDoesNotExist(previous_dev_branch_name)
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

    def _create_integration_branches(self, repo):
        integration_branches = []
        for version in self.target_versions:
            integration_branch = IntegrationBranch(
                repo,
                '%s/%s/%s' % (self.settings['integration_branch']['prefix'],
                              version,
                              self.source_branch.name),
                '%s/%s' % (self.settings['development_branch']['prefix'],
                           version)
            )
            if not integration_branch.exists():
                integration_branch.create(
                    integration_branch.development_branch)
            integration_branches.append(integration_branch)
        return integration_branches

    def _check_history_did_not_change(self, integration_branch):
        feature_branch = FeatureBranch(
            integration_branch.subname,
            self.settings['feature_branch']['prefix']
        )
        development_branch = integration_branch.development_branch
        for commit in integration_branch.get_all_commits(feature_branch):
            if not development_branch.includes_commit(commit):
                raise BranchHistoryMismatch(
                    commit=commit,
                    integration_branch=integration_branch,
                    feature_branch=feature_branch,
                    development_branch=development_branch
                )

    def _update_integration_from_dev(self, integration_branches):
        # The first integration branch should not contain commits
        # that are not in development/* or in the feature branch.
        self._check_history_did_not_change(integration_branches[0])
        for integration_branch in integration_branches:
            integration_branch.merge_from_branch(
                integration_branch.development_branch)

    def _update_integration_from_feature(self, integration_branches):
        branch_to_merge_from = self.source_branch
        for integration_branch in integration_branches:
            integration_branch.merge_from_branch(branch_to_merge_from)
            branch_to_merge_from = integration_branch

    def _create_pull_requests(self, integration_branches):
        return [integration_branch.
                create_pull_request(self.main_pr, self.bbrepo) for
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

        # If a tester is the author of the PR we will bypass the tester approval
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
            raise AuthorApprovalRequired(pr=self.main_pr,
                                         child_prs=child_prs)

        if not approved_by_peer:
            raise PeerApprovalRequired(pr=self.main_pr,
                                       child_prs=child_prs)

        if not approved_by_tester:
            raise TesterApprovalRequired(pr=self.main_pr,
                                         child_prs=child_prs)

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
            raise BuildNotStarted(pr_id=worst_pr['id'])
        elif g_state == 'INPROGRESS':
            raise BuildInProgress(pr_id=worst_pr['id'])
        assert build_state == 'SUCCESSFUL'

    def handle_pull_request(self, reference_git_repo='',
                            no_comment=False, interactive=False):

        self._check_pr_state()

        dst_branch_name = self.main_pr['destination']['branch']['name']
        src_branch_name = self.main_pr['source']['branch']['name']

        self._check_if_ignored(src_branch_name, dst_branch_name)

        # read comments and store them for multiple usage
        comments_ = self.main_pr.get_comments()
        comments = [com for com in comments_]

        self._send_greetings(comments)
        self._get_options(comments)
        self._handle_commands(comments)

        if self.option_is_set('wait'):
            raise NothingToDo('wait option is set')

        self._build_target_versions(dst_branch_name)
        self._setup_source_branch(src_branch_name, dst_branch_name)
        self._setup_destination_branches(src_branch_name, dst_branch_name)
        self._check_compatibility_src_dest()
        self._jira_checks()

        with self._clone_git_repo(reference_git_repo) as repo:
            self._check_git_repo_health(repo)
            integration_branches = self._create_integration_branches(repo)
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

        raise SuccessMessage(versions=[x.version for x in
                                       integration_branches],
                             issue=self.source_branch.jira_issue_id,
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
            Option(priviledged=True,
                   value='bypass_peer_approval' in args.cmd_line_options,
                   help="Bypass the pull request author's approval"),
        'bypass_author_approval':
            Option(priviledged=True,
                   value='bypass_author_approval' in args.cmd_line_options,
                   help="Bypass the pull request peer's approval"),
        'bypass_tester_approval':
            Option(priviledged=True,
                   value='bypass_tester_approval' in args.cmd_line_options,
                   help="Bypass the pull request tester's approval"),
        'bypass_jira_check':
            Option(priviledged=True,
                   value='bypass_jira_check' in args.cmd_line_options,
                   help="Bypass the Jira issue check"),
        'bypass_build_status':
            Option(priviledged=True,
                   value='bypass_build_status' in args.cmd_line_options,
                   help="Bypass the build and test status"),
        'bypass_commit_size':
            Option(priviledged=True,
                   value='bypass_commit_size' in args.cmd_line_options,
                   help='Bypass the check on the size of the changeset '
                        '```TBA```'),
        'unanimity':
            Option(priviledged=False,
                   value='unanimity' in args.cmd_line_options,
                   help="Change review acceptance criteria from "
                        "`one reviewer at least` to `all reviewers` "
                        "```TBA```"),
        'wait':
            Option(priviledged=False,
                   value='wait' in args.cmd_line_options,
                   help="Instruct Wall-E not to run until further notice")
    }
    return options


def setup_commands():
    commands = {
        'help':
            Command(priviledged=False,
                    handler='print_help',
                    help='print Wall-E\'s manual in the pull-request'),
        'status':
            Command(priviledged=False,
                    handler='publish_status_report',
                    help='print Wall-E\'s current status in '
                         'the pull-request ```TBA```'),
        'build':
            Command(priviledged=False,
                    handler='command_not_implemented',
                    help='re-start a fresh build ```TBA```'),
        'clear':
            Command(priviledged=False,
                    handler='command_not_implemented',
                    help='remove all comments from Wall-E from the '
                         'history ```TBA```'),
        'reset':
            Command(priviledged=False,
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
                   args.owner, args.slug, args.pull_request_id,
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
