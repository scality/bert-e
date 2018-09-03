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

import re

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Regexp

from bert_e.jobs.create_branch import CreateBranchJob

from ..base import APIEndpoint, APIForm


BRANCH_REGEXP = '^development/(\d+)\.(\d+)$|^stabilization/(\d+)\.(\d+)\.(\d+)$'  # noqa
BRANCH_FROM_REGEXP = '^[a-fA-F0-9]*$|^development/(\d+)\.(\d+)$'


class BranchForm(FlaskForm):
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
    form_cls = BranchForm
    title = 'Create new destination branch'
    help_text = '''
        <p>Create a job that will push a new GitWaterFlow destination branch
        to the repository. Supported destination branches are development
        branches (development/x.y) and stabilization branches
        (stabilization/x.y.z).</p>

        <p>The branching source point may optionally be specified by inputing
        the name of an existing development branch or a commit sha1 in the
        form. If not specified, the following rules apply:</p>

        <ul>
        <li>stabilization branches are branched off from the corresponding
        development branch,</li>
        <li>development branches are branched off from the preceeding
        development branch,</li>
        <li><strong>unless</strong> the new branch becomes the first
        development branch in the GitWaterFlow cascade; in this case the
        branch is branched off from the first development branch.</li>
        </ul>

        <p>Before the branch is created, Bert-E will check that the shape of
        the repository, including the new branch, respects the constraints of
        GitWaterFlow. If not the case, the job will fail and the repository
        left untouched.</p>

        <p>Creating a new destination branch has the following impact on
        existing queued data:</p>

        <ul>
        <li>creating a stabilization branch has no impact on queued pull
        requests; the queues are left intact and will be merged when
        build results are received,</li>
        <li>creating a development branch at the end of the GWF branch
        cascade, will trigger a reboot of the queue; all PRs that were
        in the queue will be re-evaluated (this, in effect, will force the
        automatic creation of new integration branches, and, if builds are
        successful, the pull requests will enter the new queue again without
        additionnal user interaction),</li>
        <li>attempting to create a development branch at the start or
        the middle of the GWF branch cascade, while there are pull requests
        in the queues, is not permitted; in order to protect pull requests
        forward-port conflict resolutions, it is necessary to wait for the
        queue to be empty, or alternatively, trigger a force merge, before
        attempting to create a new intermediary development branch.
        </li>
        </ul>

        <p>This job can also be activated on api endpoint
        <strong>/api/branches/&lt;branch&gt;[POST]</strong>.</p>
        '''
    form_inner_html = '''
        {{ form.branch.label }}: {{ form.branch(size=12) }}<br>
        {{ form.branch_from.label }}: {{ form.branch_from(size=12) }}<br>
        <button type="submit">create</button>
        '''
