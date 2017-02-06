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
from bert_e.utils import Dispatcher


class DispA(Dispatcher):
    pass


class DispB(Dispatcher):
    pass


@DispA.register('foo')
def foo_a():
    return 'foo'


@DispA.register('bar')
def bar_a():
    return 'bar'


@DispB.register('foo')
def foo_b():
    return 'foo'


@DispB.register('baz')
def baz_b():
    return 'baz'


def test_dispatcher_simple():
    """Check simple dispatching functionality.

    * One can register callbacks to a key in a dispatcher.
    * One can use the 'dispatch' method of a dispatcher to recover the
      callback.
    * Independent dispatcher's callbacks are separated.

    """

    disp_a = DispA()
    disp_b = DispB()
    keys_a = set(disp_a.dispatcher.keys())
    keys_b = set(disp_b.dispatcher.keys())

    assert keys_a == {'foo', 'bar'}
    assert keys_b == {'foo', 'baz'}
    assert disp_a.dispatch('foo') is foo_a
    assert disp_b.dispatch('foo') is foo_b

    # Call the functions so pytest won't complain about uncovered lines
    for disp, keys in ((disp_a, keys_a), (disp_b, keys_b)):
        for key in keys:
            assert disp.dispatch(key)() == key


class Base(Dispatcher):
    pass


class Specialized(Base):
    pass


@Base.register('foo')
def foo_base():
    return 'foo'


@Base.register('bar')
def bar_base():
    return 'bar'


@Specialized.register('foo')
def foo_spec():
    return 'foo'


@Specialized.register('baz')
def baz_spec():
    return 'baz'


def test_callback_inheritance():
    """Check inheritance of dispatcher callbacks.

    * Inheriting from a dispatcher gives access to its callbacks.
    * Inherited callbacks can be overloaded.
    * Overloading a callback doesn't affect the base dispatcher.

    """
    base = Base()
    spec = Specialized()
    keys_base = set(base.dispatcher.keys())
    keys_spec = set(spec.dispatcher.keys())

    assert keys_base == {'foo', 'bar'}         # base has expected callbacks
    assert keys_spec == {'foo', 'bar', 'baz'}  # 'bar' is inherited
    assert spec.dispatch('foo') is foo_spec    # 'foo' is overloaded in spec
    assert base.dispatch('foo') is foo_base    # base's 'foo' is intact

    for disp, keys in ((base, keys_base), (spec, keys_spec)):
        for key in keys:
            assert disp.dispatch(key)() == key
