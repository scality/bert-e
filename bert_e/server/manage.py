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

"""This module defines the repository management web page."""

import os

from flask import Blueprint, render_template, request

from .auth import requires_auth
from .api import FORMS


APPLICATION_ROOT = os.getenv('APPLICATION_ROOT', '/')
blueprint = Blueprint('management page', __name__, url_prefix=APPLICATION_ROOT)


@blueprint.route('/manage/<string:error>', methods=['GET'])
@blueprint.route('/manage', methods=['GET'], defaults={'error': None})
@requires_auth()
def display(error):
    return render_template(
        'manage.html',
        navigation=request.args.get('navoff', True),
        forms=FORMS,
        form_error=error,
    ), 200
