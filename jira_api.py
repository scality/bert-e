from jira import JIRA
from os import sys

class JiraIssue:
    def __init__(self, login, passwd):
        self._credentials = (login, passwd)
        self._jira = JIRA('https://scality.atlassian.net', basic_auth=self._credentials)

    def issue_info(self, issue_id):
        issue = self._jira.issue(issue_id)
        return(issue.fields)

if __name__ == '__main__':
    if len(sys.argv) == 4:
        test = JiraIssue(sys.argv[2], sys.argv[3])
        print(test.issue_info(sys.argv[1]))
    else:
        print('Wrong Usage')
