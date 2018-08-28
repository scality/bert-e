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

from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired, NumberRange

from bert_e.api import EvalPullRequestJob

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
    def validate_endpoint_data(pr_id):
        if pr_id < 1:
            raise ValueError()


class EvalPullRequestForm(APIForm):
    endpoint_cls = EvalPullRequest
    form_cls = PullRequestForm
    title = 'Evaluate pull request'
    help_text = '''
        <p>Create a job that will evaluate a single pull request and attempt
        at merging it.</p>

        <p>The result is equivalent to commenting a pull request and waking
        Bert-E up through a webhook, without the comment and without the
        webhook.  This can be used for example in cron'd scripts to wake up
        Bert-E regularly on open pull requests.</p>

        <p>This can also be activated on api endpoint <strong>/api/
        pull-requests/&lt;id&gt;</strong>.</p>
        '''
    form_inner_html = '''
        {{ form.pr_id.label }}: {{ form.pr_id(size=3) }}
        <button type="submit">evaluate</button>
        '''
