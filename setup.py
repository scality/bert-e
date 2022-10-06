#!/usr/bin/env python3

from os.path import abspath, dirname, join
from os import getenv
import pip

from setuptools import setup


# Besides not advised,
# https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program
# That's the only sane way to parse requirements.txt
pip_major_version = int(pip.__version__.split(".")[0])
if pip_major_version >= 20:
    from pip._internal.network.session import PipSession
    from pip._internal.req import parse_requirements
elif pip_major_version >= 10:
    from pip._internal.download import PipSession
    from pip._internal.req import parse_requirements
else:
    from pip.download import PipSession
    from pip.req import parse_requirements

CWD = dirname(abspath(__file__))


def requires():
    reqs_file = join(CWD, 'requirements.txt')
    reqs_install = parse_requirements(reqs_file, session=PipSession())

    try:
        return [str(ir.requirement) for ir in reqs_install]
    except AttributeError:
        print('attributeError')
        return [str(ir.req) for ir in reqs_install]


setup(
    name='bert-e',
    version=getenv('GITHUB_REF_NAME'),
    description='Scality\'s automated branch merging tool',
    url='https://github.com/scality/bert-e',
    license='Apache',
    include_package_data=True,
    packages=[
        'bert_e',
        'bert_e.jobs',
        'bert_e.lib',
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
        ],
    }
)
