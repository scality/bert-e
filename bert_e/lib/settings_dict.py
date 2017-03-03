# Copyright 2016 Scality
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Chainable settings dictionary with direct attribute access."""
from collections import ChainMap


class SettingsDict:
    """A ChainMap-like object that handles direct attibute access."""

    def __init__(self, *args, **kwargs):
        self._wrapped = ChainMap(*args, **kwargs)

    def __getattr__(self, attr):
        if attr.startswith('_'):
            return super().__getattr__(attr)
        instance_dict = self.__dict__
        if attr in instance_dict:
            return instance_dict[attr]
        else:
            try:
                return self._wrapped[attr]
            except KeyError as err:
                raise AttributeError(err) from err

    def __setattr__(self, attr, val):
        if attr.startswith('_'):
            super().__setattr__(attr, val)
        else:
            self._wrapped[attr] = val

    def __getitem__(self, key):
        return self._wrapped[key]

    def __setitem__(self, key, val):
        self._wrapped[key] = val

    def __contains__(self, key):
        return key in self._wrapped

    @property
    def maps(self):
        return self._wrapped.maps

    def setdefault(self, key, val):
        return self._wrapped.setdefault(key, val)

    def get(self, key, default=None):
        return self._wrapped.get(key, default)

    def update(self, other):
        return self._wrapped.update(other)
