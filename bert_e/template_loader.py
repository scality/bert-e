#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import os.path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def render(template, **kwargs):
    abs_dir = os.path.dirname(os.path.realpath(__file__))
    tfile = os.path.join(abs_dir, 'templates')
    env = Environment(loader=FileSystemLoader(tfile),
                      undefined=StrictUndefined)
    return env.get_template(template).render(**kwargs)