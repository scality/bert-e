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
"""Utility functions to work with marshmallow schemas."""

from marshmallow import ValidationError, Schema


class SchemaError:
    """Base class of all schema related errors."""
    pass


def load(cls: Schema, data, **kwargs):
    """Load data using given schema class.

    Raises:
        SchemaError if the data doesn't match the schema.

    Return:
        The result of data loading: either a trimmed dictionary, or
        the result of any @post_load processing.

    """
    res, errors = cls(**kwargs).load(data)
    if errors:
        raise SchemaError(errors)
    return res


def validate(cls: Schema, data, **kwargs):
    """Validate data against given schema class.

    Raises:
        SchemaError if the data doesn't match the schema.

    """
    try:
        cls(**kwargs).validate(data)
    except ValidationError as err:
        raise SchemaError(err.messages) from err


def dumps(cls: Schema, data, **kwargs):
    """Validate data against given schema and dump it to a json string.

    Raises:
        SchemaError if the data doesn't match the schema.

    """
    schema = cls(**kwargs)
    try:
        schema.validate(data)
    except ValidationError as err:
        raise SchemaError(err.messages) from err
    res, _ = schema.dumps(data)
    return res
