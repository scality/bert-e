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
"""Cache implementation using *Least Recently Used* (LRU) strategy.

An LRU cache is a fix sized cache that disposed of the least recently added
(or accessed) entries first.

"""
from collections import OrderedDict


class LRUCache(object):
    """Simple LRU cache implementation."""

    def __init__(self, size=1000):
        """Build a new LRUCache.

        Args:
            - size (int): size of the cache. Defaults to 1000 items

        """
        self._size = size
        self._dict = OrderedDict()

    def get(self, key, default=None):
        """Get an item from the cache.

        Args:
            - key (hashable): key of the item to get.
            - default: default value to return if key is absent.

        Returns:
            The value associated to the key, of default value if absent.

        """
        try:
            self._dict.move_to_end(key)
            return self._dict[key]
        except KeyError:
            return default

    def set(self, key, val):
        """Add an item into the cache.

        If key is already present, move it to top and replace its value.
        Else, make room in the cache for the new value, by deleting old
        entries.

        Args:
            - key (hashable): key of the new object
            - val: value to associate to the key

        Returns:
            val.
        """

        try:
            # Key is in cache. Move it to top.
            self._dict.move_to_end(key)
        except KeyError:
            # Key is not in cache. Make room for it.
            while len(self._dict) > self._size - 1:
                self._dict.popitem(last=False)
        self._dict[key] = val
        return val

    @property
    def size(self) -> int:
        """Size of the cache."""
        return self._size

    @size.setter
    def size(self, val: int):
        """Setting the size property of the cache allows to redimension it."""
        self._size = val
        while len(self._dict) > val:
            self._dict.popitem(last=False)
