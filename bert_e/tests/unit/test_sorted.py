
from functools import cmp_to_key
from collections import OrderedDict
from bert_e.workflow.gitwaterflow.branches import (
    DevelopmentBranch,
    StabilizationBranch,
    HotfixBranch,
    compare_branches
)
from pytest import fixture
from bert_e.lib.versions import version_key


@fixture(scope='function')
def branches():
    branches = OrderedDict()
    branches[2, 0] = {
        DevelopmentBranch: None,
        StabilizationBranch: None,
        HotfixBranch: None,
    }
    branches[1, None] = {
        DevelopmentBranch: None,
        StabilizationBranch: None,
        HotfixBranch: None,
    }
    branches[1, 0] = {
        DevelopmentBranch: None,
        StabilizationBranch: None,
        HotfixBranch: None,
    }
    branches[1, 1] = {
        DevelopmentBranch: None,
        StabilizationBranch: None,
        HotfixBranch: None,
    }
    return branches


def test_sorted_with_branches(branches):

    sorted_branches = OrderedDict(
        sorted(branches.items(), key=cmp_to_key(compare_branches)))
    assert list(sorted_branches.keys()) == [(1, 0), (1, 1), (1, None), (2, 0)]


def test_sorted_versions():
    versions = [
        '1.0.0', '1.0.1', '1.1.0', '1.1.1',
        '2.0.0', '2', '1.0', '3', '1.0.0.3'
    ]
    expected = [
        '3', '2', '2.0.0', '1.1.1', '1.1.0',
        '1.0', '1.0.1', '1.0.0', '1.0.0.3'
    ]
    sorted_versions = sorted(versions, key=version_key, reverse=True)

    assert sorted_versions == expected
