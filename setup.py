#!/usr/bin/env python3

from os.path import abspath, dirname, join
from setuptools import setup
from subprocess import PIPE, Popen
import sys


CWD = dirname(abspath(__file__))


def version():
    p = Popen(['git', 'describe', '--tags', '--always'], stdout=PIPE, cwd=CWD)
    out = p.communicate()[0]
    if sys.version_info[0] > 2:
        out = out.decode()
    return out.strip()


def requires():
    with open(join(CWD, 'requirements.txt'), 'r') as fp:
        return fp.read().split()


setup(
    name='bert-e',
    version=version(),
    description='Scality\'s automated branch merging tool',
    url='https://bitbucket.org/scality/bert-e',
    license='Apache',
    include_package_data=True,
    packages=[
        'bert_e',
        'bert_e.api',
        'bert_e.bin',
    ],
    install_requires=requires(),
    entry_points={
        'console_scripts': [
            'bert-e=bert_e.bert_e:main',
            'bert-e-serve=bert_e.__main__:serve',
            'filter_pull_requests=bert_e.bin.filter_pull_requests:main',
            'nobuildstatus=bert_e.bin.nobuildstatus:main',
            'webhook_parser=bert_e.bin.webhook_parser:main',
            'webhook_register=bert_e.bin.webhook_register:main',
        ],
    }
)
