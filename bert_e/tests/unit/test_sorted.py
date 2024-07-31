
from functools import cmp_to_key
from collections import OrderedDict
from bert_e.workflow.gitwaterflow.branches import DevelopmentBranch, StabilizationBranch, HotfixBranch, compare_branches


def test_sorted_with_branches():
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

    sorted_branches = OrderedDict(sorted(branches.items(), key=cmp_to_key(compare_branches)))
    assert list(sorted_branches.keys()) == [(1, 0), (1, 1), (1, None), (2, 0)]
