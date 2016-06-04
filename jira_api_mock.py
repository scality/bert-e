from random import randint


class FixVersion(object):
    def __init__(self, name, key):
        self.name = name
        self.id = key


class IssueType(object):
    def __init__(self):
        self.name = 'Bug'


class Fields(object):
    def __init__(self):
        self.fixVersions = []
        self.issuetype = IssueType()


class Issue(object):

    def __init__(self, issue_id, login, passwd):
        # fields = {u'fixVersions': [{u'name':u'5.1.4', u'id':u'10693'},
        #                           {u'name':u'6.0.1', u'id':u'10800'}],
        #          u'issuetype': u'Bug'}
        self.fields = Fields()
        self.key = issue_id

    def update(self, fields):
        assert len(fields) == 1
        self.fields.fixVersions = []
        for fv in fields['fixVersions']:
            for key, val in fv.items():
                assert key == 'name'
                self.fields.fixVersions.append(FixVersion(val, str(randint)))

first_issue = Issue('RING-00001', None, None)
first_issue.update(fields={'fixVersions': [
    {'name': '5.1.4'},
    {'name': '6.0.1'}]})
jira_issues = {
    'RING-00001': first_issue
}


def add_issue(key):
    jira_issues[key] = Issue(key, None, None)


def JiraIssue(issue_id, login, passwd):
    return jira_issues[issue_id]
