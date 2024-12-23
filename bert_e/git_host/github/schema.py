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
"""This module holds the schema declarations for the Github API's objects.

/!\\ The schema declared in this module is not meant to be exhaustive. Only the
"interesting" subsets of these objects (the attributes that are likely to be
used by Bert-E) are declared.

"""
from marshmallow import Schema, fields, EXCLUDE


class GitHubSchema(Schema):
    class Meta:
        unknown = EXCLUDE


class User(GitHubSchema):
    id = fields.Int(required=True)
    login = fields.Str(required=True)
    # Note: the "printable" name can be absent in most API call results.
    # When it is the case, login should be used instead.
    name = fields.Str()
    type = fields.Str()


class Repo(GitHubSchema):
    name = fields.Str(required=True)
    owner = fields.Nested(User, required=True)
    full_name = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    private = fields.Bool()
    git_url = fields.Str()
    clone_url = fields.Url()
    default_branch = fields.Str()


class CreateRepo(GitHubSchema):
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


class Status(GitHubSchema):
    state = fields.Str(required=True)
    target_url = fields.Str(required=True, allow_none=True)
    description = fields.Str(required=True, allow_none=True)
    context = fields.Str(required=True)


class AggregatedStatus(GitHubSchema):
    # The most convenient way to get a pull request's build status is to
    # query github's API for an aggregated status.
    state = fields.Str()
    sha = fields.Str()
    repository = fields.Nested(Repo)
    statuses = fields.Nested(Status, many=True, required=True)


class Branch(GitHubSchema):
    label = fields.Str()  # user:ref or org:ref
    ref = fields.Str()
    sha = fields.Str()
    user = fields.Nested(User)
    repo = fields.Nested(Repo)


class App(GitHubSchema):
    id = fields.Int()
    slug = fields.Str()
    owner = fields.Nested(User)
    name = fields.Str()
    description = fields.Str()


class CheckSuite(GitHubSchema):
    id = fields.Integer()
    head_sha = fields.Str()
    head_branch = fields.Str()
    html_url = fields.Url()
    created_at = fields.DateTime()
    status = fields.Str()
    conclusion = fields.Str(allow_none=True)
    repository = fields.Nested(Repo)
    app = fields.Nested(App)


class AggregateCheckSuites(GitHubSchema):
    total_count = fields.Integer()
    check_suites = fields.Nested(CheckSuite, many=True)


class Output(GitHubSchema):
    title = fields.Str()
    summary = fields.Str()
    text = fields.Str(allow_none=True)


class CheckRun(GitHubSchema):
    id = fields.Integer()
    head_sha = fields.Str()
    status = fields.Str()
    conclusion = fields.Str(allow_none=True)
    output = fields.Nested(Output)
    html_url = fields.Url()
    name = fields.Str()


class CreateCheckRun(GitHubSchema):
    name = fields.Str()
    head_sha = fields.Str()
    status = fields.Str()
    conclusion = fields.Str(allow_none=True)
    output = fields.Nested(Output)


class WorkflowRun(GitHubSchema):
    id = fields.Integer()
    head_sha = fields.Str()
    head_branch = fields.Str()
    status = fields.Str()
    conclusion = fields.Str(allow_none=True)
    check_suite_id = fields.Integer()
    html_url = fields.Str()
    event = fields.Str()
    repository = fields.Nested(Repo)
    workflow_id = fields.Integer()


class AggregateWorkflowRuns(GitHubSchema):
    total_count = fields.Integer()
    workflow_runs = fields.Nested(WorkflowRun, many=True)


class AggregateCheckRuns(GitHubSchema):
    total_count = fields.Integer()
    check_runs = fields.Nested(CheckRun, many=True)


class PullRequest(GitHubSchema):
    number = fields.Int(required=True)
    url = fields.Url()
    html_url = fields.Url()
    comments_url = fields.Url()
    review_comments_url = fields.Url()
    state = fields.Str()
    title = fields.Str()
    body = fields.Str(allow_none=True)
    user = fields.Nested(User, allow_none=True)
    head = fields.Nested(Branch)  # source branch
    base = fields.Nested(Branch)  # destination branch
    created_at = fields.DateTime()
    updated_at = fields.DateTime(allow_none=True)
    closed_at = fields.DateTime(allow_none=True)
    merged_at = fields.DateTime(allow_none=True)


class CreatePullRequest(GitHubSchema):
    title = fields.Str(required=True)
    head = fields.Str(required=True)
    base = fields.Str(required=True)
    body = fields.Str()
    maintainer_can_modify = fields.Bool()


class UpdatePullRequest(GitHubSchema):
    title = fields.Str()
    body = fields.Str()
    state = fields.Str()
    base = fields.Str()
    maintainer_can_modify = fields.Bool()


class Comment(GitHubSchema):
    id = fields.Int(required=True)
    body = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime(allow_none=True)
    user = fields.Nested(User)
    url = fields.Url()


class CreateComment(GitHubSchema):
    body = fields.Str(required=True)


class Review(GitHubSchema):
    id = fields.Int(allow_none=True)
    body = fields.Str(allow_none=True)
    commit_id = fields.Str()
    state = fields.Str()
    user = fields.Nested(User)


class DraftReview(GitHubSchema):
    path = fields.Str()
    position = fields.Int()
    body = fields.Str()


class CreateReview(GitHubSchema):
    body = fields.Str(allow_none=True)
    event = fields.Str()


class PullRequestEvent(GitHubSchema):
    action = fields.Str(required=True)
    number = fields.Int()
    pull_request = fields.Nested(PullRequest)


class Issue(GitHubSchema):
    number = fields.Int()
    title = fields.Str()
    # If this dict is present and non-empty, then the issue is a pull request.
    pull_request = fields.Dict(optional=True, default={})


class IssueCommentEvent(GitHubSchema):
    action = fields.Str()
    issue = fields.Nested(Issue)


class PullRequestReviewEvent(GitHubSchema):
    action = fields.Str()
    pull_request = fields.Nested(PullRequest)


class StatusEvent(GitHubSchema):
    sha = fields.Str()
    state = fields.Str()
    context = fields.Str()
    description = fields.Str(allow_none=True)
    target_url = fields.Str(allow_none=True)


class CheckSuiteEvent(GitHubSchema):
    action = fields.Str()
    check_suite = fields.Nested(CheckSuite)
    repository = fields.Nested(Repo)
