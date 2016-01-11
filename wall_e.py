#!/usr/bin/env python
# -*- coding: utf-8 -*-

import smtplib
import time
import traceback
import sys
import argparse
import re
import logging
import requests
from template_loader import render
from collections import OrderedDict

from bitbucket_api import (Repository as BitBucketRepository,
                           Client)
from git_api import Repository as GitRepository, Branch, MergeFailedException
from jira_api import JiraIssue
from wall_e_exceptions import (NotMyJobException,
                               PrefixCannotBeMergedException,
                               BranchDoesNotAcceptFeaturesException,
                               BranchNameInvalidException,
                               ConflictException,
                               CommentAlreadyExistsException,
                               NothingToDoException,
                               AuthorApprovalRequiredException,
                               PeerApprovalRequiredException,
                               BuildFailedException,
                               BuildNotStartedException,
                               BuildInProgressException,
                               WallE_Exception,
                               WallE_InternalException,
                               WallE_SilentException,
                               WallE_TemplateException,
                               ImproperEmailFormatException,
                               UnableToSendEmailException,
                               HelpException)

KNOWN_VERSIONS = OrderedDict([
    ('4.3', '4.3.18'),
    ('5.1', '5.1.4'),
    ('6.0', '6.0.0')
])

JIRA_ISSUE_BRANCH_PREFIX = {
    'Epic': 'project',
    'Story': 'feature',
    'Bug': 'bugfix',
    'Improvement': 'improvement'
}

WALL_E_USERNAME = 'scality_wall-e'
WALL_E_EMAIL = 'wall_e@scality.com'

RELEASE_ENGINEERS = [
    WALL_E_USERNAME,   # we need this for test purposes
    'anhnp',
    'bertrand_demiddelaer_scality',
    'ludovicmaillard',
    'mcolzi',
    'mouhamet7',
    'mvaude',
    'pierre_louis_bonicoli',
    'rayene_benrayana',
    'sylvain_killian',
]


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
    members of RELEASE_ENGINEERS will be able to activate
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
    members of RELEASE_ENGINEERS will be able to activate
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
        raise ImproperEmailFormatException("The specified email does "
                                           "not seem valid (%s)" % destination)
    try:
        smtplib.SMTP('localhost')
    except Exception as excp:
        raise UnableToSendEmailException("Unable to send email (%s)" % excp)


def send_email(destination, title, content):
    """Send some data by email."""
    match_ = re.match("(?P<short_name>[^@]*)@.*", destination)
    if not match_:
        raise ImproperEmailFormatException("The specified email does "
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


class ScalBranch(Branch):
    def __init__(self, name):
        Branch.__init__(self, name)
        if '/' not in name:
            raise BranchNameInvalidException(name)


class DestinationBranch(ScalBranch):
    def __init__(self, name):
        ScalBranch.__init__(self, name)
        self.prefix, self.version = name.split('/', 1)
        if (self.prefix != 'development' or
                self.version not in KNOWN_VERSIONS.keys()):
            raise BranchNameInvalidException(name)

        self.impacted_versions = OrderedDict(
            [(version, release) for (version, release) in
                KNOWN_VERSIONS.items()
                if version >= self.version])


class FeatureBranch(ScalBranch):
    def __init__(self, name):
        ScalBranch.__init__(self, name)
        self.prefix, self.subname = name.split('/', 1)
        self.jira_issue_id = None
        match = re.match('(?P<issue_id>[A-Z]+-\d+).*', self.subname)
        if match:
            self.jira_issue_id = match.group('issue_id')
        else:
            logging.warning('%s does not contain a correct '
                            'issue id number', self.name)
            # Fixme : send a comment instead ? or ignore the jira checks ?

    def merge_cascade(self, destination_branch):
        if self.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(source=self,
                                                destination=destination_branch)
        if (self.prefix == 'feature' and
                destination_branch.version in ['4.3', '5.1']):
            raise BranchDoesNotAcceptFeaturesException(
                source=self,
                destination=destination_branch)

        previous_feature_branch = self
        new_pull_requests = []
        for version in destination_branch.impacted_versions:
            integration_branch = (FeatureBranch('w/%s/%s/%s'
                                  % (version, self.prefix, self.subname)))
            try:
                (integration_branch
                 .update_or_create_and_merge(previous_feature_branch))
            except MergeFailedException:
                raise ConflictException(source=integration_branch,
                                        destination=previous_feature_branch)
            development_branch = DestinationBranch('development/' + version)
            try:
                integration_branch.merge(development_branch)
            except MergeFailedException:
                raise ConflictException(source=integration_branch,
                                        destination=development_branch)
            integration_branch.push()
            new_pull_requests.append((integration_branch, development_branch))
            previous_feature_branch = integration_branch
        return new_pull_requests


class WallE:
    def __init__(self, bitbucket_login, bitbucket_password, bitbucket_mail,
                 owner, slug, pull_request_id, options, commands):
        self._bbconn = Client(bitbucket_login,
                              bitbucket_password, bitbucket_mail)
        self.bbrepo = BitBucketRepository(self._bbconn, owner=owner,
                                          repo_slug=slug)
        self.original_pr = (self.bbrepo
                            .get_pull_request(pull_request_id=pull_request_id))
        self.options = options
        self.commands = commands

    def option_is_set(self, name):
        if name not in self.options.keys():
            return False
        return self.options[name].is_set()

    def check_build_status(self, pr, key):
        if self.option_is_set('bypass_build_status'):
            return
        try:
            build_state = self.bbrepo.get_build_status(
                revision=pr['source']['commit']['hash'],
                key=key
            )['state']
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise BuildNotStartedException(pr['id'])
            raise
        else:
            if build_state == 'FAILED':
                raise BuildFailedException(pr['id'])
            elif build_state == 'INPROGRESS':
                raise BuildInProgressException(pr['id'])
            assert build_state == 'SUCCESSFUL'

    def find_bitbucket_comment(self,
                               username=None,
                               startswith=None,
                               max_history=None):
        # the last comment posted is the first in the list
        for index, comment in enumerate(self.original_pr.get_comments()):
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
                           interactive=False):
        logging.debug('considering sending: %s', msg)

        if no_comment:
            logging.debug('not sending message due to no_comment being True.')
            return

        # if wall-e doesn't do anything in the last 10 comments,
        # allow him to run again
        if self.find_bitbucket_comment(username=WALL_E_USERNAME,
                                       startswith=msg,
                                       max_history=10):

            raise CommentAlreadyExistsException('The same comment has '
                                                'already been posted by '
                                                'Wall-E in the past. '
                                                'Nothing to do here!')

        if interactive:
            print('%s\n' % msg)
            if not confirm('Do you want to send this comment?'):
                return

        logging.info('SENDING MSG %s', msg)

        self.original_pr.add_comment(msg)

    def jira_checks(self, source_branch, destination_branch):
        """performs checks using the Jira issue id specified in the source
        branch name"""
        if (self.option_is_set('bypass_jira_version_check') and
                self.option_is_set('bypass_jira_type_check')):
            return

        if not source_branch.jira_issue_id:
            if destination_branch.version in ['6.0', 'trunk']:
                # We do not want to merge in maintenance branches without
                # proper ticket handling but it is OK for future releases.
                # FIXME : versions should not be hardcoded
                return

            raise WallE_Exception('You want to merge `%s` into a maintenance '
                                  'branch but this branch does not specify a '
                                  'Jira issue id' % (source_branch.name))

        issue = JiraIssue(issue_id=source_branch.jira_issue_id,
                          login='wall_e',
                          passwd=self._bbconn.auth.password)

        # Use parent task instead
        if issue.fields.issuetype.name == 'Sub-task':
            issue = JiraIssue(issue_id=issue.fields.parent.key,
                              login='wall_e',
                              passwd=self._bbconn.auth.password)

        # Fixme : add proper error handling
        # What happens when the issue does not exist ? -> comment on PR ?
        # What happens in case of network failure ? -> fail silently ?
        # What else can happen ?
        if not self.option_is_set('bypass_jira_type_check'):
            issuetype = issue.fields.issuetype.name
            expected_prefix = JIRA_ISSUE_BRANCH_PREFIX.get(issuetype)
            if expected_prefix is None:
                raise WallE_InternalException('Jira issue: unknow type %r' %
                                              issuetype)
            if expected_prefix != source_branch.prefix:
                raise WallE_Exception('branch prefix name %r mismatches '
                                      'jira issue type field %r' %
                                      (source_branch.prefix, expected_prefix))

        if not self.option_is_set('bypass_jira_version_check'):
            issue_versions = set([version.name for version in
                                  issue.fields.fixVersions])
            expect_versions = set(
                destination_branch.impacted_versions.values())
            if issue_versions != expect_versions:
                raise WallE_Exception("The issue 'Fix Version/s' field "
                                      "contains %s. It must contain: %s." %
                                      (', '.join(issue_versions),
                                       ', '.join(expect_versions)))

    def handle_pull_request(self, reference_git_repo='', no_comment=False,
                            interactive=False):

        if self.original_pr['state'] != 'OPEN':  # REJECTED or FULFILLED
            raise NothingToDoException('The pull-request\'s state is "%s"'
                                       % self.original_pr['state'])

        # must be called before any options is checked
        self.get_comments_options()

        self.handle_commands()

        # TODO: Check the size of the diff and issue warnings

        # TODO: Check build status

        # TODO: make it idempotent

        dst_brnch_name = self.original_pr['destination']['branch']['name']
        src_brnch_name = self.original_pr['source']['branch']['name']
        try:
            destination_branch = DestinationBranch(dst_brnch_name)
        except BranchNameInvalidException as e:
            logging.info('Destination branch %r not handled, ignore PR %s',
                         e.branch, self.original_pr['id'])
            # Nothing to do
            raise NotMyJobException(src_brnch_name, dst_brnch_name)

        try:
            source_branch = FeatureBranch(
                self.original_pr['source']['branch']['name'])
        except BranchNameInvalidException as e:
            raise PrefixCannotBeMergedException(e.branch)

        if source_branch.prefix == 'hotfix':
            # hotfix branches are ignored, nothing todo
            logging.info("Ignore branch %r", source_branch.name)
            return

        if source_branch.prefix not in ['feature', 'bugfix', 'improvement']:
            raise PrefixCannotBeMergedException(source_branch.name)

        self.jira_checks(source_branch, destination_branch)

        git_repo = GitRepository(self.bbrepo.get_git_url())
        git_repo.clone(reference_git_repo)

        git_repo.config('user.email', '"%s"'
                        % self._bbconn.mail)
        git_repo.config('user.name', '"Wall-E"')

        new_pull_requests = source_branch.merge_cascade(destination_branch)

        # Create integration PR
        child_prs = []
        author = self.original_pr['author']['username']
        for source_branch, destination_branch in new_pull_requests:
            title = ('[%s] #%s: %s'
                     % (destination_branch.name,
                        self.original_pr['id'], self.original_pr['title']))

            description = render('pull_request_description.md',
                                 pr=self.original_pr)
            pr = self.bbrepo.create_pull_request(
                title=title,
                name='name',
                source={'branch': {'name': source_branch.name}},
                destination={'branch': {'name': destination_branch.name}},
                close_source_branch=True,
                reviewers=[{'username': author}],
                description=description
            )
            child_prs.append(pr)

        # Check parent PR: approval
        self.check_approval(child_prs)

        # Check integration PR: build status
        for pr in child_prs:
            self.check_build_status(pr, 'jenkins_build')
            self.check_build_status(pr, 'jenkins_utest')

        if interactive and not confirm('Do you want to merge ?'):
            return

        for pr in child_prs:
            pr.merge()

    def check_options(self, author, keyword_list):
        logging.debug('checking keywords %s', keyword_list)

        for keyword in keyword_list:
            if keyword not in self.options.keys():
                logging.debug('ignoring keywords in this comment due to '
                              'an unknown keyword `%s`', keyword_list)
                return False

            limited_access = self.options[keyword].priviledged
            if limited_access and author not in RELEASE_ENGINEERS:
                logging.debug('ignoring keywords in this comment due to '
                              'unsufficient credentials `%s`', keyword_list)
                return False

        return True

    def get_comments_options(self):
        """Load settings from pull-request comments."""
        for index, comment in enumerate(self.original_pr.get_comments()):
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
                                'Unknown format: %s' % raw)
                continue

            keywords = match_.group('keywords').strip().split()

            if not self.check_options(author, keywords):
                logging.warning('Keyword comment ignored. '
                                'Checks failed: %s' % raw)
                continue

            for keyword in keywords:
                self.options[keyword].set(True)

    def check_command(self, author, command):
        logging.debug('checking command %s', command)

        if command not in self.commands.keys():
            logging.debug('ignoring command in this comment due to '
                          'an unknown command `%s`', command)
            return False

        limited_access = self.commands[command].priviledged
        if limited_access and author not in RELEASE_ENGINEERS:
            logging.debug('ignoring command in this comment due to '
                          'unsufficient credentials `%s`', command)
            return False

        return True

    def handle_commands(self):
        """Detect the last command in pull-request comments and act on it."""
        for index, comment in enumerate(self.original_pr.get_comments()):
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

            if not self.check_command(author, command):
                logging.warning('Command comment ignored. '
                                'Checks failed: %s' % raw)
                continue

            # get command handler and execute it
            assert hasattr(self, self.commands[command].handler)
            handler = getattr(self, self.commands[command].handler)
            handler(match_.group('args'))

    def check_approval(self, child_prs):
        approved_by_author = self.option_is_set('bypass_author_approval')
        approved_by_peer = self.option_is_set('bypass_peer_approval')

        if approved_by_author and approved_by_peer:
            return

        # NB: when author hasn't approved the PR, author isn't listed in
        # 'participants'
        for participant in self.original_pr['participants']:
            if not participant['approved']:
                continue
            author = self.original_pr['author']['username']
            if participant['user']['username'] == author:
                approved_by_author = True
            else:
                approved_by_peer = True

        if not approved_by_author:
            raise AuthorApprovalRequiredException(pr=self.original_pr,
                                                  child_prs=child_prs)

        if not approved_by_peer:
            raise PeerApprovalRequiredException(pr=self.original_pr,
                                                child_prs=child_prs)

    def print_help(self, args):
        raise HelpException('to do')


def main():
    parser = argparse.ArgumentParser(add_help=False,
                                     description='Merges bitbucket '
                                                 'pull requests.')
    bypass_author_approval_help = 'Bypass the pull request author\'s approval'
    bypass_author_peer_help = 'Bypass the pull request peer\'s approval'
    bypass_jira_version_check_help = 'Bypass the Jira fixVersions field check'
    bypass_jira_type_check_help = 'Bypass the build and test status'
    bypass_build_status_help = 'Bypass the Jira issueType field check'

    parser.add_argument(
        '--bypass-author-approval', action='store_true', default=False,
        help=bypass_author_approval_help)
    parser.add_argument(
        '--bypass-peer-approval', action='store_true', default=False,
        help=bypass_author_peer_help)
    parser.add_argument(
        '--bypass-jira-version-check', action='store_true', default=False,
        help=bypass_jira_version_check_help)
    parser.add_argument(
        '--bypass-jira-type-check', action='store_true', default=False,
        help=bypass_jira_type_check_help)
    parser.add_argument(
        '--bypass-build-status', action='store_true', default=False,
        help=bypass_build_status_help)
    parser.add_argument(
        'pull_request_id',
        help='The ID of the pull request')
    parser.add_argument(
        'password',
        help='Wall-E\'s password [for Jira and Bitbucket]')
    parser.add_argument(
        '--reference-git-repo', default='',
        help='Reference to a local git repo to improve cloning delay')
    parser.add_argument(
        '--owner', default='scality',
        help='The owner of the repo (default: scality)')
    parser.add_argument(
        '--slug', default='ring',
        help='The repo\'s slug (default: ring)')
    parser.add_argument(
        '--interactive', action='store_true', default=False,
        help='Ask before merging or sending comments')
    parser.add_argument(
        '--no-comment', action='store_true', default=False,
        help='Do not add any comment to the pull request page')
    parser.add_argument(
        '-v', action='store_true', dest='verbose', default=False,
        help='Verbose mode')
    parser.add_argument(
        '--alert-email', action='store', default=None, type=str,
        help='Where to send notifications in case of '
             'incorrect behaviour')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.alert_email:
        try:
            setup_email(args.alert_email)
        except ImproperEmailFormatException:
            print("Invalid email (%s)" % args.alert_email)
            sys.exit(1)
        except UnableToSendEmailException:
            print("It appears I won't be able to send emails, please check "
                  "the email server.")
            sys.exit(1)

    options = {
        'bypass_peer_approval':
            Option(priviledged=True,
                   value=args.bypass_peer_approval,
                   help=bypass_author_approval_help),
        'bypass_author_approval':
            Option(priviledged=True,
                   value=args.bypass_author_approval,
                   help=bypass_author_peer_help),
        'bypass_jira_version_check':
            Option(priviledged=True,
                   value=args.bypass_jira_version_check,
                   help=bypass_jira_version_check_help),
        'bypass_jira_type_check':
            Option(priviledged=True,
                   value=args.bypass_jira_type_check,
                   help=bypass_jira_type_check_help),
        'bypass_build_status':
            Option(priviledged=True,
                   value=args.bypass_build_status,
                   help=bypass_build_status_help)
    }

    commands = {
        'help':
            Command(priviledged=False,
                    handler='print_help',
                    help='print Wall-E\'s manual in the pull-request')
    }

    wall_e = WallE(WALL_E_USERNAME, args.password, WALL_E_EMAIL,
                   args.owner, args.slug, args.pull_request_id,
                   options, commands)

    try:
        wall_e.handle_pull_request(
            reference_git_repo=args.reference_git_repo,
            no_comment=args.no_comment,
            interactive=args.interactive
        )

    except (WallE_Exception, WallE_TemplateException) as excp:
        wall_e.send_bitbucket_msg(str(excp),
                                  no_comment=args.no_comment,
                                  interactive=args.interactive)
        raise

    except WallE_SilentException as excp:
        raise

    except Exception:
        if args.alert_email:
            send_email(destination=args.alert_email,
                       title="[Wall-E] Unexpected termination "
                             "(%s)" % time.asctime(),
                       content=traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
