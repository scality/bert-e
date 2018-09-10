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

from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired, NumberRange

from bert_e.jobs.eval_pull_request import EvalPullRequestJob

from .base import APIEndpoint, APIForm


class PullRequestForm(FlaskForm):
    pr_id = IntegerField(
        'pr id', validators=[DataRequired(), NumberRange(min=1)])


class EvalPullRequest(APIEndpoint):
    rule = '/pull-requests/<int:pr_id>'
    method = 'POST'
    admin = False
    job = EvalPullRequestJob

    @staticmethod
    def validate_endpoint_data(pr_id, json):
        if pr_id < 1:
            raise ValueError()


class EvalPullRequestForm(APIForm):
    doc = '/pull-requests/pr_id'
    endpoint_cls = EvalPullRequest
    form_cls = PullRequestForm
    title = 'Evaluate a pull request'
    help_text = '''
        <p>Create a job that will evaluate a single pull request and attempt
        at merging it.</p>
        '''
    form_inner_html = '''
        <input id="pr_id" name="pr_id" placeholder="pull request id"
        class="form-control" required>
        <button type="submit" class="btn btn-outline-danger
        btn-block">evaluate</button>
        '''
