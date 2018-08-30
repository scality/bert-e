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

"""This module registers the server api endpoints."""

from flask import Markup, render_template_string

from .jobs import GetJob, ListJobs
from .gwf.queues import (DeleteQueues, DeleteQueuesForm,
                         ForceMergeQueues, ForceMergeQueuesForm,
                         RebuildQueues, RebuildQueuesForm)
from .pull_requests import EvalPullRequest, EvalPullRequestForm


"""All API Endpoints."""
ENDPOINTS = [
    GetJob,
    ListJobs,
    EvalPullRequest,
    ForceMergeQueues,
    RebuildQueues,
    DeleteQueues,
]

"""All API forms. Order is respected in management page."""
FORMS = [
    EvalPullRequestForm,
    ForceMergeQueuesForm,
    RebuildQueuesForm,
    DeleteQueuesForm,
]


def configure(app):
    for endpoint in ENDPOINTS:
        app.register_blueprint(endpoint.as_blueprint())

    for form in FORMS:
        app.register_blueprint(form.as_blueprint())

    @app.context_processor
    def utility_api_form():
        def _render_form(view):
            form_html = '''
                <form action="{{ url_for(endpoint) }}" method="post"
                onsubmit="return confirm(
                'Are you sure you want to create this job?');">
                %s
                {{ form.csrf_token }}
                </form>
            ''' % view.form_inner_html
            rendered = render_template_string(
                form_html,
                endpoint=view.endpoint,
                form=view.form_cls()
            )
            return Markup(rendered)
        return dict(render_form=_render_form)
