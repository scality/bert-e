# Copyright 2016 Scality
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
"""This module holds the schema declarations for the Github API's objects.

/!\ The schema declared in this module is not meant to be exhaustive. Only the
"interesting" subsets of these objects (the attributes that are likely to be
used by Bert-E) are declared.

"""
from marshmallow import Schema, fields, ValidationError

from .. import base


class SchemaError(base.Error):
    """Base class of all schema related errors."""
    pass


def load(schema_cls, data, **kwargs):
    """Load data using given schema class.

    Raises:
        SchemaError if the data doesn't match the schema.

    Return:
        The result of data loading: either a trimmed dictionary, or any
        the result of any @post_load processing.

    """
    res, errors = schema_cls(**kwargs).load(data)
    if errors:
        raise SchemaError(errors)
    return res


def validate(schema_cls, data, **kwargs):
    """Validate data against given schema class.

    Raises:
        SchemaError if the data doesn't match the schema.

    """
    try:
        schema_cls(**kwargs).validate(data)
    except ValidationError as err:
        raise SchemaError(err.messages) from err


def dumps(schema_cls, data, **kwargs):
    """Validate data against given schema and dump it to a json string.

    Raises:
        SchemaError if the data doesn't match the schema.

    """
    schema = schema_cls(**kwargs)
    try:
        schema.validate(data)
    except ValidationError as err:
        raise SchemaError(err.messages) from err
    res, _ = schema.dumps(data)
    return res


class User(Schema):
    id = fields.Int(required=True)
    login = fields.Str(required=True)
    # Note: the "printable" name can be absent in most API call results.
    # When it is the case, login should be used instead.
    name = fields.Str()
    type = fields.Str()


class Repo(Schema):
    name = fields.Str(required=True)
    owner = fields.Nested(User, required=True)
    full_name = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    private = fields.Bool()
    git_url = fields.Str()
    clone_url = fields.Url()
    default_branch = fields.Str()


class CreateRepo(Schema):
    name = fields.Str(required=True)
    description = fields.Str()
    homepage = fields.Url()
    private = fields.Bool()
    has_issues = fields.Bool()
    has_wiki = fields.Bool()
    team_id = fields.Int()
    auto_init = fields.Bool()
    gitignore_template = fields.Str()
    licence_template = fields.Str()


class Status(Schema):
    state = fields.Str(required=True)
    target_url = fields.Str(required=True, allow_none=True)
    description = fields.Str(required=True, allow_none=True)
    context = fields.Str(required=True)


class AggregatedStatus(Schema):
    # The most convenient way to get a pull request's build status is to
    # query github's API for an aggregated status.
    state = fields.Str()
    sha = fields.Str()
    repository = fields.Nested(Repo)
    statuses = fields.Nested(Status, many=True, required=True)


class Branch(Schema):
    label = fields.Str()  # user:ref or org:ref
    ref = fields.Str()
    sha = fields.Str()
    user = fields.Nested(User)
    repo = fields.Nested(Repo)


class PullRequest(Schema):
    number = fields.Int(required=True)
    url = fields.Url()
    comments_url = fields.Url()
    review_comments_url = fields.Url()
    state = fields.Str()
    title = fields.Str()
    body = fields.Str(allow_none=True)
    assignee = fields.Nested(User, allow_none=True)
    head = fields.Nested(Branch)  # source branch
    base = fields.Nested(Branch)  # destination branch
    created_at = fields.DateTime()
    updated_at = fields.DateTime(allow_none=True)
    closed_at = fields.DateTime(allow_none=True)
    merged_at = fields.DateTime(allow_none=True)


class CreatePullRequest(Schema):
    title = fields.Str(required=True)
    head = fields.Str(required=True)
    base = fields.Str(required=True)
    body = fields.Str()
    maintainer_can_modify = fields.Bool()


class UpdatePullRequest(Schema):
    title = fields.Str()
    body = fields.Str()
    state = fields.Str()
    base = fields.Str()
    maintainer_can_modify = fields.Bool()


class Comment(Schema):
    id = fields.Int(required=True)
    body = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime(allow_none=True)
    user = fields.Nested(User)


class CreateComment(Schema):
    body = fields.Str(required=True)


class Review(Schema):
    id = fields.Int(allow_none=True)
    body = fields.Str(allow_none=True)
    commit_id = fields.Str()
    state = fields.Str()
    user = fields.Nested(User)


class DraftReview(Schema):
    path = fields.Str()
    position = fields.Int()
    body = fields.Str()


class CreateReview(Schema):
    body = fields.Str(allow_none=True)
    event = fields.Str()