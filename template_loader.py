#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def render(template, **kwargs):
    abs_dir = os.path.dirname(os.path.realpath(__file__))
    tfile = os.path.join(abs_dir, 'templates')
    env = Environment(loader=FileSystemLoader(tfile),
                      undefined=StrictUndefined)
    return env.get_template(template).render(**kwargs)
