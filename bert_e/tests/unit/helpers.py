"""Shared test helpers for unit tests."""


class FakeRepo:
    """Minimal git-repo stub that satisfies GWFBranch.__init__."""
    def __init__(self):
        self._url = ''
        self._remote_branches = {}

    def cmd(self, *args, **kwargs):
        return ''
