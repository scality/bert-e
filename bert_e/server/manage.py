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

"""This module defines the repository management web page."""

from flask import Blueprint, redirect, render_template, url_for

from .auth import requires_auth
from .form import SingleButtonForm


blueprint = Blueprint('management page', __name__)


@blueprint.route('/manage', methods=['GET', 'POST'])
@requires_auth()
def display():
    rebuild_queues_form = SingleButtonForm()
    if rebuild_queues_form.validate_on_submit():
        return redirect(url_for("api.rebuild_queues"))

    return render_template(
        'manage.html', rebuild_queues_form=rebuild_queues_form), 200
