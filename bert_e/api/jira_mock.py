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


class Issue(object):
    def __init__(self, name, key):
        self.name = name
        self.id = key


class IssueType(object):
    def __init__(self):
        self.name = 'Bug'


class Fields(object):
    def __init__(self):
        self.fixVersions = []
        self.fixVersions.append(Issue('5.1.4', '10693'))
        self.fixVersions.append(Issue('6.0.1', '10800'))
        self.issuetype = IssueType()


class JiraIssue(object):
    def __init__(self, account_url, issue_id, login, passwd):
        # fields = {u'fixVersions': [{u'name':u'5.1.4', u'id':u'10693'},
        #                           {u'name':u'6.0.1', u'id':u'10800'}],
        #          u'issuetype': u'Bug'}
        self.fields = Fields()
        self.key = issue_id
