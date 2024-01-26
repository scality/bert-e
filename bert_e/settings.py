from os.path import exists, join

import yaml
import logging
import os
from marshmallow import (
    Schema, fields, post_load, pre_load, validates_schema, ValidationError,
    EXCLUDE)

from bert_e.exceptions import (IncorrectSettingsFile,
                               SettingsFileNotFound,
                               MalformedSettings)
from bert_e.lib.settings_dict import SettingsDict


class BertEContextFilter(logging.Filter):
    """This is a filter which will inject Bert-E contextual
    information into the log.

    """
    def __init__(self, settings):
        self.settings = settings

    def filter(self, record):
        record.instance = "{host}-{owner}-{slug}".format(
            host=self.settings['repository_host'],
            owner=self.settings['repository_owner'],
            slug=self.settings['repository_slug']
        )
        return True


class Username(fields.Str):
    def _deserialize(self, value, attr, data, **kwargs):
        return value.lower()


class UserDict(SettingsDict):

    def __repr__(self):
        repr = "<User(username=%s, account_id=%s)>" %\
            (self.username, self.account_id)
        return repr

    def __hash__(self):
        if self.account_id:
            return hash(self.account_id)
        return hash(self.username)

    def __str__(self):
        return str(self.username)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            if other.account_id and self.account_id:
                return other.account_id == self.account_id
            return other.username == self.username

        elif isinstance(other, str):
            return other == self.account_id or other == self.username
        else:
            raise ValueError('Comparing %s with %s' %
                             (self.__class__, type(other)))

    def lower(self):
        return self.__str__().lower()


class UserSettingSchema(Schema):
    username = Username(required=True)
    account_id = fields.Str(required=False, load_default=None)

    @pre_load
    def split_usernames(self, username, **kwargs):
        data = iter(username.split('@'))
        user = dict(username=None, account_id=None)
        user['username'] = next(data, None)
        user['account_id'] = next(data, None)
        return user

    @post_load
    def output(self, data, **kwargs):
        return UserDict(data)


class PrAuthorsOptions(fields.Dict):
    BYPASS_LIST = [
        'bypass_author_approval',
        'bypass_jira_check',
        'bypass_build_status',
        'bypass_commit_size',
        'bypass_incompatible_branch',
        'bypass_peer_approval',
        'bypass_leader_approval',
    ]

    def serialize(self, value, attr=None, obj=None, **kwargs):
        data = super(PrAuthorsOptions, self).serialize(value, attr, obj)
        res = dict()
        for user, values in data.items():
            res[user] = [key for key, value in data.items() if value]

        return res

    def deserialize(self, value, attr=None, data=None, **kwargs):
        data = super(PrAuthorsOptions, self).deserialize(value, attr, data)

        found_elem = []
        res = dict()
        for user, bypass_list in data.items():
            for elem in bypass_list:
                if elem in self.BYPASS_LIST:
                    found_elem.append(elem)
                else:
                    raise IncorrectSettingsFile(
                        f'This bypass does not exist: {elem}'
                    )

            res[user] = dict([
                (key, key in bypass_list) for key in self.BYPASS_LIST
            ])
        return res


class SettingsSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    # Settings defined in config files
    always_create_integration_pull_requests = fields.Bool(
        required=False, load_default=True)
    always_create_integration_branches = fields.Bool(
        required=False, load_default=True)

    frontend_url = fields.Str(required=False, load_default='')

    repository_owner = fields.Str(required=True)
    repository_slug = fields.Str(required=False, load_default=None)

    repository_host = fields.Str(required=True)

    robot = fields.Nested(UserSettingSchema, required=True)
    robot_email = fields.Str(required=True)

    pull_request_base_url = fields.Str(required=False)
    commit_base_url = fields.Str(required=False)

    build_key = fields.Str(required=False, load_default="pre-merge")

    need_author_approval = fields.Bool(required=False, load_default=True)
    required_leader_approvals = fields.Int(required=False, load_default=0)
    required_peer_approvals = fields.Int(required=False, load_default=2)
    pr_author_options = PrAuthorsOptions(load_default={})

    jira_account_url = fields.Str(required=False, load_default='')
    jira_email = fields.Str(required=False, load_default='')
    jira_keys = fields.List(fields.Str(), required=False, load_default=[])

    prefixes = fields.Dict(required=False, load_default={})
    bypass_prefixes = fields.List(fields.Str(), load_default=[])

    disable_version_checks = fields.Bool(required=False, load_default=False)

    organization = fields.Str(load_default='')
    admins = fields.Nested(
        UserSettingSchema, many=True, load_default=[])
    project_leaders = fields.Nested(
        UserSettingSchema, many=True, load_default=[])
    tasks = fields.List(fields.Str(), load_default=[])

    max_commit_diff = fields.Int(required=False, load_default=0)

    bitbucket_addon_base_url = fields.Str(required=False, load_default='')
    bitbucket_addon_client_id = fields.Str(required=False, load_default='')
    bitbucket_addon_url = fields.Str(required=False, load_default='')

    # Settings coming from CLI arguments
    robot_password = fields.Str(required=False, load_default='')
    jira_token = fields.Str(required=False, load_default='')

    backtrace = fields.Bool(required=False, load_default=False)
    interactive = fields.Bool(required=False, load_default=False)
    no_comment = fields.Bool(required=False, load_default=False)
    quiet = fields.Bool(required=False, load_default=False)
    disable_queues = fields.Bool(required=False, load_default=False)
    use_queues = fields.Bool(required=False, load_default=True)
    skip_queue_when_possible = fields.Bool(required=False, load_default=False)
    cmd_line_options = fields.List(fields.Str(), load_default=[])

    client_id = fields.Str(required=False, load_default='')
    client_secret = fields.Str(required=False, load_default='')

    @pre_load(pass_many=True)
    def load_env(self, data, **kwargs):
        """Load environment variables"""
        for key, value in os.environ.items():
            if key.startswith('BERT_E_'):
                data[key[7:].lower()] = value
        return data

    # # beyond individual setting validity,
    # # check now for inter-settings validity

    @validates_schema
    def validate_inter_settings(self, data, **kwargs):
        errors = {}
        if (data['required_leader_approvals'] >
                data['required_peer_approvals']):
            errors['required_leader_approvals'] = [
                'required_peer_approvals must be equal to, '
                'or exceed, required_leader_approvals'
            ]
        if (data['required_leader_approvals'] >
                len(data['project_leaders'])):
            errors['required_leader_approvals'] = [
                'the number of project leaders must be equal to, '
                'or exceed, the value of required_leader_approvals'
            ]
        if errors:
            raise ValidationError(errors)

    @post_load(pass_many=True)
    def base_url(self, data, **kwargs):
        """Add base urls for repository, commits and pull requests."""

        if "repository_host_url" not in data:
            hosts = {
                'bitbucket': 'https://bitbucket.org',
                'github': 'https://github.com',
                'mock': 'https://bitbucket.org',
            }
            if data["repository_host"] in hosts:
                data["repository_host_url"] = hosts[data["repository_host"]]
            else:
                raise IncorrectSettingsFile(
                    f'Unknown repository host: {data["repository_host"]}'
                )

        if "pull_request_base_url" not in data:

            data["pull_request_base_url"] = join(
                data["repository_host_url"],
                data["repository_owner"],
                data["repository_slug"],
                "pull/{pr_id}"
            )

        if "commit_base_url" not in data:
            data["commit_base_url"] = join(
                data["repository_host_url"],
                data["repository_owner"],
                data["repository_slug"],
                "commits/{commit_id}"
            )

        return data

    @post_load
    def mk_settings(self, data, **kwargs):
        """Return the settings as a python object."""

        return SettingsDict(data)


def setup_settings(settings_file: str) -> dict:
    """Load and checks settings from a yaml file.

    Args:
        - settings_file (str): path of the yaml file to load.

    Raises:
        - SettingsFileNotFound
        - IncorrectSettingsFile if the yaml syntax can't be parsed
        - MalformedSettings if one or more fields from the settings are
                            incorrect (wrong types or missing values)

    Returns:
        The settings as a deserialized yaml object.

    """
    if not exists(settings_file):
        raise SettingsFileNotFound(settings_file)

    with open(settings_file, 'r') as f:
        try:
            # read the yaml data as pure string (no conversion)
            data = yaml.load(f, Loader=yaml.BaseLoader)
        except Exception as err:
            raise IncorrectSettingsFile(settings_file) from err

    try:
        settings = SettingsSchema().load(data)
    except IncorrectSettingsFile as exp:
        raise exp
    except Exception as exp:
        raise MalformedSettings(settings_file, exp, data) from exp

    return settings
