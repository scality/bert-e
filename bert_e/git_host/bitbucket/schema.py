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
"""This module holds the schema declarations for the Github API's objects.

/!\\ The schema declared in this module is not meant to be exhaustive. Only the
"interesting" subsets of these objects (the attributes that are likely to be
used by Bert-E) are declared.

"""
from marshmallow import Schema, fields


class Comment(Schema):
    content = fields.Dict()
    created_on = fields.DateTime()
    updated_on = fields.DateTime(allow_none=True)
    user = fields.Dict(allow_none=True)
    links = fields.Dict()
    deleted = fields.Boolean()
    type_ = fields.String(load_from='type', dump_to='type')
    pullrequest = fields.Dict()


class CreateComment(Schema):
    content = fields.Dict(required=True)
