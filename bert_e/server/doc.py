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

"""This module defines the documentation web pages."""

import os

from pathlib import Path

from flask import Blueprint, abort, render_template, request
from flaskext.markdown import Markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.smart_strong import SmartEmphasisExtension
from markdown.extensions.smarty import SmartyExtension
from markdown.extensions.tables import TableExtension

APPLICATION_ROOT = os.getenv('APPLICATION_ROOT', '/')
blueprint = Blueprint('doc', __name__, url_prefix=APPLICATION_ROOT)


@blueprint.route('/doc/<string:docname>', methods=['GET'])
def display(docname):
    basename = '%s_DOC.md' % docname.upper()
    filename = Path(__file__).parent.parent / 'docs' / basename

    try:
        with open(filename, 'r') as file_:
            content = file_.read()
    except EnvironmentError:
        abort(404)

    return render_template(
        'doc.html',
        navigation=request.args.get('navoff', True),
        name=docname,
        content=content,
    ), 200


def configure(app):
    """Configure Markdown for Bert-E's Flask server."""
    md = Markdown(app)
    md.register_extension(CodeHiliteExtension)
    md.register_extension(FencedCodeExtension)
    md.register_extension(SmartEmphasisExtension)
    md.register_extension(SmartyExtension)
    md.register_extension(TableExtension)
