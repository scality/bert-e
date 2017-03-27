#!/usr/bin/env python3

from os.path import abspath, dirname, join

from setuptools import setup

CWD = dirname(abspath(__file__))


def requires():
    with open(join(CWD, 'requirements.txt'), 'r') as fp:
        return fp.read().split()


setup(
    name='bert-e',
    use_scm_version={
        'local_scheme': 'dirty-tag'
    },
    setup_requires=[
        'setuptools_scm'
    ],
    description='Scality\'s automated branch merging tool',
    url='https://bitbucket.org/scality/bert-e',
    license='Apache',
    include_package_data=True,
    packages=[
        'bert_e',
        'bert_e.api',
        'bert_e.lib',
        'bert_e.bin',
        'bert_e.git_host',
        'bert_e.git_host.github',
        'bert_e.workflow',
        'bert_e.workflow.gitwaterflow',
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
