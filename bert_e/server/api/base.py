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

"""This module defines the server api endpoints."""

import logging
import requests

from flask import (Blueprint, Response, current_app,
                   redirect, request, session, url_for)
from flask.views import View
from flask_wtf import FlaskForm

from bert_e.job import APIJob

from ..auth import invalid, requires_auth


LOG = logging.getLogger(__name__)


class BaseView(View):
    """Abstract Flask view with blueprint registration capabilities."""

    admin = False
    """bool: does the endpoint require admin level access."""

    endpoint = None
    """str: the full name of the view (auto-populated)."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.endpoint = cls.__name__ + '.' + cls.__name__

    @classmethod
    def as_blueprint(cls):
        """Registration method."""
        bp = Blueprint(cls.__name__, cls.__module__, url_prefix=cls.url_prefix)
        auth_decorator = requires_auth(cls.admin)
        view = auth_decorator(cls.as_view(cls.__name__))
        bp.add_url_rule(
            cls.rule,
            endpoint=cls.__name__,
            methods=(cls.method,),
            view_func=view
        )
        return bp

    def dispatch_request(self, *args, **kwargs):
        """Flask View dispatcher."""
        return self.view(*args, **kwargs)

    def view(self, *args, **kwargs):
        raise NotImplementedError()  # TODO replace with abstract


class APIEndpoint(BaseView):
    """Flask View for API endpoints."""

    url_prefix = '/api'
    """str: the prefix of all API endpoints."""

    rule = ''
    """str: the rule of the endpoint."""

    method = ''
    """str: the accepted HTTP method."""

    job = None
    """APIJob: he job triggered by the API endpoint."""

    def __init_subclass__(cls, **kwargs):
        """Runs some health checks on class properties."""
        super().__init_subclass__(**kwargs)
        assert cls.rule
        assert type(cls.rule) == str
        assert cls.method in ['GET', 'DELETE', 'PATCH', 'POST', 'PUT']
        assert type(cls.admin) == bool
        if cls.view == APIEndpoint.view:
            assert issubclass(cls.job, APIJob)

    @staticmethod
    def validate_endpoint_data(*args, **kwargs):
        """Raise ValueError if kwargs contain invalid data."""
        pass

    def view(self, *args, **kwargs):
        """Flask view of the API endpoint."""
        json = request.get_json() or {}
        user = session['user']
        LOG.info("Received order %r from user %r (%s, %s, %s)",
                 self.__class__.__name__,
                 user,
                 args, kwargs, json)
        try:
            self.validate_endpoint_data(*args, **kwargs, json=json)
        except ValueError:
            return invalid()

        job = self.job(kwargs=kwargs, user=user,
                       settings=json, bert_e=current_app.bert_e)
        current_app.bert_e.put_job(job)

        return Response(job.as_json(), 202, {'Content-Type': 'text/json'})


class APIForm(BaseView):
    """Flask View for API forms."""

    url_prefix = '/form'
    """str: the prefix of all form callbacks."""

    method = 'POST'
    """str: the method of all form callbacks."""

    endpoint_cls = None
    """APIEndpoint: the APIEnpoint class this form refers to."""

    form_cls = FlaskForm
    """FlaskForm: the form class to represent on management view."""

    title = ''
    """str: title of section on management page."""

    help_text = ''
    """str: help section of section on management page."""

    doc = ''
    """str: name of an anchor in the API doc to refer to."""

    form_inner_html = ''
    """str: content of the HTML form on management page."""

    def __init_subclass__(cls, **kwargs):
        """Runs some health checks on class properties."""
        super().__init_subclass__(**kwargs)
        assert issubclass(cls.endpoint_cls, APIEndpoint)
        assert issubclass(cls.form_cls, FlaskForm)
        assert cls.title
        assert type(cls.title) == str
        assert cls.help_text
        assert type(cls.help_text) == str
        assert cls.form_inner_html
        assert type(cls.form_inner_html) == str
        assert cls.method == 'POST'

        cls.rule = cls.__name__
        cls.admin = cls.endpoint_cls.admin

    def _build_data(self, form_data):
        """Build url data and json data from form inputs.

        Returns:
          - url_data (dict): form data that must be passed
              in the URL in the future API call

          - json_data (dict): form data that must be
              passed as Json to the API call

        """
        url_data = dict()
        json_data = dict()
        form_data.pop('csrf_token')
        for key in form_data:
            if current_app.url_map.is_endpoint_expecting(
                    self.endpoint_cls.endpoint, key):
                url_data[key] = form_data[key]
                continue

            json_data[key] = form_data[key]

        return url_data, json_data

    def view(self, *args, **kwargs):
        """Flask view of the form callback."""
        form = self.form_cls()
        if form.validate_on_submit():
            url_data, json_data = self._build_data(form.data)
            headers = dict(request.headers)
            headers['Content-Type'] = 'application/json'
            response = requests.request(
                self.endpoint_cls.method,
                url_for(self.endpoint_cls.endpoint,
                        **url_data,
                        _external=True),
                json=json_data,
                headers=headers
            )
            if response.status_code == 202:
                return redirect(url_for('status page.display'), code=302)

        return redirect(url_for('management page.display',
                                error=self.form_cls.__name__,
                                _anchor=self.form_cls.__name__),
                        code=302)
