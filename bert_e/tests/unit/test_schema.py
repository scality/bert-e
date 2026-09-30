import pytest
from marshmallow import Schema, fields

from bert_e.lib.schema import SchemaError, load


class _Schema(Schema):
    name = fields.Str(required=True)


def test_schema_error_str_returns_string():
    err = SchemaError({'name': ['Missing data for required field.']})
    assert str(err) == "{'name': ['Missing data for required field.']}"
    assert err.errors == {'name': ['Missing data for required field.']}


def test_load_raises_printable_schema_error():
    with pytest.raises(SchemaError) as excinfo:
        load(_Schema, {})
    assert 'name' in str(excinfo.value)
