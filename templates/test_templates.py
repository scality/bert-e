#!/usr/bin/env python
# -*- coding: utf-8 -*-

from jinja2 import Environment, FileSystemLoader

def generate_fake_child_pr(version):
    return {
        'id': 2,
        'source': {'branch': {'name': 'w/%s/feature/RING-1234'%version}},
        'destination': {'branch': {'name': 'development/%s'%version}}
    }

def generate_fake_main_pr(version):
    return {
        'id': 1,
        'author': {'username' : 'sam'},
        'source': {'branch': {'name': '/feature/RING-1234'}},
        'destination': {'branch': {'name': 'development/%s'%version}}
    }


class W:
    pass

wall_e = W()
wall_e.main_pr = generate_fake_main_pr('4.3')
wall_e.child_pull_requests = [
    generate_fake_child_pr('5.1'),
    generate_fake_child_pr('6.0')]


print Environment(loader=FileSystemLoader('.')).\
    get_template('need_approval.md').render(wall_e=wall_e)

