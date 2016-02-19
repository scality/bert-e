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
    def __init__(self, issue_id, login, passwd):
        #fields = {u'fixVersions': [{u'name':u'5.1.4', u'id':u'10693'},
        #                           {u'name':u'6.0.1', u'id':u'10800'}],
        #          u'issuetype': u'Bug'}
        self.fields = Fields()
        self.key = issue_id
