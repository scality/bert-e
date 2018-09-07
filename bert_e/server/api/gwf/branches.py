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

import re

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Regexp

from bert_e.jobs.create_branch import CreateBranchJob
from bert_e.jobs.delete_branch import DeleteBranchJob

from ..base import APIEndpoint, APIForm


BRANCH_REGEXP = '^development/(\d+)\.(\d+)$|^stabilization/(\d+)\.(\d+)\.(\d+)$'  # noqa
BRANCH_FROM_REGEXP = '^[a-fA-F0-9]*$|^development/(\d+)\.(\d+)$'


class CreateBranchForm(FlaskForm):
    branch = StringField(
        'new branch name',
        validators=[
            DataRequired(),
            Regexp(regex=BRANCH_REGEXP),
        ]
    )

    branch_from = StringField(
        'branch off from (optional sha1/branch name)',
        validators=[Regexp(regex=BRANCH_FROM_REGEXP)]
    )


class CreateBranch(APIEndpoint):
    rule = '/gwf/branches/<path:branch>'
    method = 'POST'
    admin = True
    job = CreateBranchJob

    @staticmethod
    def validate_endpoint_data(branch, json):
        if not re.match(BRANCH_REGEXP, branch):
            raise ValueError()

        if json and 'branch_from' in json:
            if not re.match(BRANCH_FROM_REGEXP, json['branch_from']):
                raise ValueError()


class CreateBranchForm(APIForm):
    endpoint_cls = CreateBranch
    form_cls = CreateBranchForm
    title = 'Create new destination branch'
    help_text = '''
        <p>Create a job that will push a new GitWaterFlow destination branch
        to the repository.</p>
        '''
    form_inner_html = '''
        {{ form.branch.label }}: {{ form.branch(size=12) }}<br>
        {{ form.branch_from.label }}: {{ form.branch_from(size=12) }}<br>
        <button type="submit">create</button>
        '''


class DeleteBranchForm(FlaskForm):
    branch = StringField(
        'branch name to delete',
        validators=[
            DataRequired(),
            Regexp(regex=BRANCH_REGEXP),
        ]
    )


class DeleteBranch(APIEndpoint):
    rule = '/gwf/branches/<path:branch>'
    method = 'DELETE'
    admin = True
    job = DeleteBranchJob

    @staticmethod
    def validate_endpoint_data(branch, json):
        if not re.match(BRANCH_REGEXP, branch):
            raise ValueError()


class DeleteBranchForm(APIForm):
    endpoint_cls = DeleteBranch
    form_cls = DeleteBranchForm
    title = 'Delete a destination branch'
    help_text = '''
        <p>Create a job that will remove a GitWaterFlow destination branch
        from the repository.</p>
        '''
    form_inner_html = '''
        {{ form.branch.label }}: {{ form.branch(size=12) }}<br>
        <button type="submit">delete</button>
        '''
