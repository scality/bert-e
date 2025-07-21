
from functools import cmp_to_key
from collections import OrderedDict
from bert_e.workflow.gitwaterflow.branches import (
    DevelopmentBranch,
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
        HotfixBranch: None,
    }
    branches[1, None] = {
        DevelopmentBranch: None,
        HotfixBranch: None,
    }
    branches[1, 0] = {
        DevelopmentBranch: None,
        HotfixBranch: None,
    }
    branches[1, 1] = {
        DevelopmentBranch: None,
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


def test_compare_branches_major_minor_vs_major_only():
    branch1 = ((4, 3),)
    branch2 = ((4, ),)
    assert compare_branches(branch1, branch2) == -1


def test_compare_branches_major_only_vs_major_only_returns_0():
    branch1 = ((4, None),)  # major-only
    branch2 = ((4, None),)     # major.only
    assert compare_branches(branch1, branch2) == 0


def test_compare_branches_major_only_vs_major_minor():
    branch1 = ((4, ),)
    branch2 = ((4, 3),)
    assert compare_branches(branch1, branch2) == 1


def test_compare_branches_major_minor_micro_vs_major_minor():
    branch1 = ((4, 3, 2),)
    branch2 = ((4, 3),)
    assert compare_branches(branch1, branch2) == -1


def test_compare_branches_major_minor_vs_major_minor_micro():
    branch1 = ((4, 3),)
    branch2 = ((4, 3, 2),)
    assert compare_branches(branch1, branch2) == 1
