#!/usr/bin/env python3

from os.path import abspath, dirname, join

from setuptools import setup

# Besides not advised,
# https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program
# That's the only sane way to parse requirements.txt
try: # for pip >= 10
    from pip._internal.download import PipSession
    from pip._internal.req import parse_requirements
except ImportError: # for pip <= 9.0.3
    from pip.download import PipSession
    from pip.req import parse_requirements

CWD = dirname(abspath(__file__))


def requires():
    reqs_file = join(CWD, 'requirements.txt')
    reqs_install = parse_requirements(reqs_file, session=PipSession())

    return [str(ir.req) for ir in reqs_install]


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
        'bert_e.jobs',
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
            'bert-e-serve=bert_e.server.server:main',
            'filter_pull_requests=bert_e.bin.filter_pull_requests:main',
            'nobuildstatus=bert_e.bin.nobuildstatus:main',
            'webhook_parser=bert_e.bin.webhook_parser:main',
            'webhook_register=bert_e.bin.webhook_register:main',
        ],
    }
)
