# Copyright 2016-2018 Scality
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
"""Dispatcher pattern implementation.

A Dispatcher is a class made extensible through callback registration.

One can register callbacks to indexable keys inside the dispatcher *class*, and
use a dispatcher *instance* to dispatch a key and get the corresponding
callback.

The Dispatcher mixin class defined in this module implements this common
pattern, with the following non-trivial features:

    - If a class inherits from a Dispatcher, it also inherits from its
      callbacks.
    - A sub-class of a Dispatcher can overload its inherited callbacks without
      interfering with the base class's callbacks.
    - A Dispatcher proposes syntaxic sugar with a @Dispatcher.register
      decorator to make its usage nicer and less invasive.

"""
from collections import ChainMap
from typing import Callable


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
    def set_callback(cls, key, callback: Callable) -> Callable:
        """Set a new callback to the dispatcher class."""
        cls.__callbacks__[key] = callback
        return callback

    @classmethod
    def register(cls, key) -> Callable:
        """Register a callback to the dispatcher class using a decorator."""
        def wrapper(callback):
            return cls.set_callback(key, callback)
        return wrapper
