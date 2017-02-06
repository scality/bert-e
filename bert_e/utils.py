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

from collections import ChainMap, deque
from time import sleep


class DispatcherMeta(type):
    """Metaclass used to define a dispatcher class."""
    def __new__(mcs, name, bases, attrs):
        callbacks = ChainMap()
        maps = callbacks.maps
        for base in bases:
            if isinstance(base, DispatcherMeta):
                maps.extend(base.__callbacks__.maps)

        attrs['__callbacks__'] = callbacks
        attrs['dispatcher'] = property(lambda obj: callbacks)
        cls = super().__new__(mcs, name, bases, attrs)
        return cls


class Dispatcher(metaclass=DispatcherMeta):
    """Dispatcher pattern mixin."""
    def dispatch(self, key, default=None):
        return self.dispatcher.get(key, default)

    @classmethod
    def set_callback(cls, key, callback):
        """Set a new callback to the dispatcher class."""
        cls.__callbacks__[key] = callback
        return callback

    @classmethod
    def register(cls, key):
        """Register a new callback to the dispatcher class with a decorator
        syntax.

        """
        def wrapper(callback):
            return cls.set_callback(key, callback)
        return wrapper


class LRUCache(object):
    """Simple LRU cache implementation."""

    def __init__(self, size=1000):
        """Build a new LRUCache.

        Args:
            * size (int): size of the cache. Defaults to 1000 items

        """
        self._size = size
        self._dict = dict()
        self._keys = deque()

    def get(self, key, default):
        """Get an item from the cache.

        Args:
            * key (hashable): key of the item to get.
            * default: default value to return if key is absent.

        Returns:
            The value associated to the key, of default value if absent.

        """
        try:
            self._keys.remove(key)
            self._keys.appendleft(key)
            return self._dict[key]
        except ValueError:
            return default

    def set(self, key, val):
        """Add an item into the cache.

        If key is already present, move it to top and replace its value.
        Else, make room in the cache for the new value, by deleting old
        entries.

        Args:
            * key (hashable): key of the new object
            * val: value to associate to the key

        """
        try:
            # Key is in cache. Move it to top.
            self._keys.remove(key)
        except ValueError:
            # Key is not in cache. Make room for it.
            while len(self._keys) > self._size - 1:
                self._dict.pop(self._keys.pop())
        self._dict[key] = val
        self._keys.appendleft(key)
        return val

    @property
    def size(self):
        """Size of the cache."""
        return self._size

    @size.setter
    def size(self, val):
        """Setting the size property of the cache allows to redimension it."""
        self._size = val
        while len(self._keys) > val:
            self._dict.pop(self._keys.pop())


class RetryTimeout(Exception):
    pass


class RetryHandler(object):
    """Class that implements an exponentially growing retry delay strategy.

    It should be used as a wrapper around a function call that might fail,
    such as network connection methods.

    """

    def __init__(self, limit=3600, logger=None, max_delay=300):
        self.limit = limit
        self._cur_delay = 1
        self._elapsed = 0
        self._log = logger
        self._max_delay = max_delay

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.reset()

    def reset(self):
        """Reset timers."""
        self._cur_delay = 1
        self._elapsed = 0

    def wait(self, err=RetryTimeout()):
        """Wait until next retry.

        If wait limit was exceeded (first try happened more than `limit`
        seconds ago), raise an error.

        Args:
            err (exception): exception to raise.

        Raise:
            RetryTimeout by default.

        """
        if self.limit is not None and self._elapsed >= self.limit:
            if self._log:
                self._log.error("Reached timeout (%ds)", self.limit)
            raise err
        sleep(self._cur_delay)
        self._elapsed += self._cur_delay
        self._cur_delay = min(self._max_delay, self._cur_delay * 2)

    def run(self, func, *args, **kwargs):
        """Wrap the execution of a callable, and retry as long as it fails and
        the wait limit wasn't reached.

        Args:
            func: the callable to run.
            catch: exception or tuple of exceptions to catch.
            fail_msg: message to log upon failure.
            *args, **kwargs: arguments to pass the callable.

        Return:
            the result of func(*args, **kwargs)

        """
        # Python 2 doesn't support mixing optional args with **kwargs syntax
        catch = kwargs.pop('catch', Exception)
        fail_msg = kwargs.pop('fail_msg',
                              "Call to '%s' failed" % func.__name__)
        while True:
            try:
                return func(*args, **kwargs)
            except catch as err:
                if self._log:
                    self._log.warning(fail_msg)
                    self._log.info("Will retry in %d seconds", self._cur_delay)
                self.wait(err)
