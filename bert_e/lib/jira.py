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

import sys

from jira import JIRA


class JiraIssue:
    def __init__(self, account_url, issue_id, email, token):
        self._credentials = (email, token)
        self._jira = JIRA(account_url, basic_auth=self._credentials)
        issue = self._jira.issue(issue_id)
        self.fields = issue.fields
        self.key = issue.key


if __name__ == '__main__':
    if len(sys.argv) == 4:
        issue = JiraIssue(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
        print(issue.fields.issuetype)
        for fv in issue.fields.fixVersions:
            print(fv)
    else:
        print('Wrong Usage')
