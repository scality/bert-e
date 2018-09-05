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


class ReverseProxied(object):
    """Wrap the application in this middleware and configure the
    front-end server to add these headers, to let you quietly bind
    this to a URL other than / and to an HTTP scheme that is
    different than what is used locally.

    args:
        - app: the WSGI application

    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', None)
        if script_name is not None:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                path_info = path_info[len(script_name):]
                environ['PATH_INFO'] = path_info

        scheme = environ.get('HTTP_X_SCHEME', None)
        if scheme is not None:
            environ['wsgi_url_scheme'] = scheme

        server = environ.get('HTTP_X_FORWARDED_SERVER', None)
        if server:
            environ['HTTP_HOST'] = server

        return self.app(environ, start_response)
