class JiraIssue:
    def __init__(self, issue_id, login, passwd):
        # TODO: create mocked dict
        fields = {u'fixVersions': [{u'name':u'5.1.4', u'id':u'10693'},
                                   {u'name':u'6.0.1', u'id':u'10800'}],
                  u'issuetype': u'Bug'}
        self.fields = fields
        self.key = issue_id
