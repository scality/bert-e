from jira import JIRA
from os import sys


class JiraIssue:
    def __init__(self, account_url, issue_id, login, passwd):
        self._credentials = (login, passwd)
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
