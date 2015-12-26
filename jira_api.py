from jira import JIRA
from os import sys


class JiraIssue:
    def __init__(self, issue_id, login, passwd):
        self._credentials = (login, passwd)
        self._jira = JIRA('https://scality.atlassian.net',
                          basic_auth=self._credentials)
        self.fields = self._jira.issue(issue_id).fields


if __name__ == '__main__':
    if len(sys.argv) == 4:
        issue = JiraIssue(sys.argv[1], sys.argv[2], sys.argv[3])
        print(issue.fields.issuetype)
        for fv in issue.fields.fixVersions:
            print fv
    else:
        print('Wrong Usage')
