# flake8: noqa

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

ACTOR = {'display_name': 'John Doe',
         'links': {'avatar': {
             'href': 'https://bitbucket.org/account/john_doe/avatar/32/'},
                    'html': {
                        'href': 'https://bitbucket.org/john_doe/'},
                    'self': {
                        'href': 'https://api.bitbucket.org/2.0/users/john_doe'}},
         'type': 'user',
         'username': 'john_doe',
         'uuid': '{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}

COMMENT = {'content': {'html': '<p>test16</p>',
                        'markup': 'markdown',
                        'raw': 'test16'},
           'created_on': '2016-07-30T14:17:11.953311+00:00',
           'id': 21710334,
           'links': {'html': {
               'href': 'https://bitbucket.org/test_owner/test_repo/pull-requests/4/_/diff#comment-21710334'},
                      'self': {
                          'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4/comments/21710334'}},
           'parent': {'id': 21710326,
                       'links': {'html': {
                           'href': 'https://bitbucket.org/test_owner/test_repo/pull-requests/4/_/diff#comment-21710326'},
                                  'self': {
                                      'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4/comments/21710326'}}},
           'pullrequest': {'id': 1,
                            'links': {'html': {
                                'href': 'https://bitbucket.org/test_owner/test_repo/pull-requests/4'},
                                       'self': {
                                           'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4'}},
                            'title': 'Bugfix/releng 1966 allow bitbucket pipeline to deploy',
                            'type': 'pullrequest'},
           'type': 'pullrequest_comment',
           'updated_on': '2016-07-30T14:17:11.954715+00:00',
           'user': {'display_name': 'John Doe',
                     'links': {'avatar': {
                         'href': 'https://bitbucket.org/account/john_doe/avatar/32/'},
                                'html': {
                                    'href': 'https://bitbucket.org/john_doe/'},
                                'self': {
                                    'href': 'https://api.bitbucket.org/2.0/users/john_doe'}},
                     'type': 'user',
                     'username': 'john_doe',
                     'uuid': '{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}}

PULL_REQUEST = {'author': {'display_name': 'Johanna Doe',
                            'links': {'avatar': {
                                'href': 'https://bitbucket.org/account/johanna_doe/avatar/32/'},
                                       'html': {
                                           'href': 'https://bitbucket.org/johanna_doe/'},
                                       'self': {
                                           'href': 'https://api.bitbucket.org/2.0/users/johanna_doe'}},
                            'type': 'user',
                            'username': 'johanna_doe',
                            'uuid': '{76527410-6118-4c2a-a1e7-274355957f0e}'},
                'close_source_branch': True,
                'closed_by': None,
                'comment_count': 11,
                'created_on': '2016-07-29T12:20:33.873540+00:00',
                'description': '* Add HTTP basic auth as fallback to IP whitelisting\r\n\r\n* Fix htpasswd encoding of ssha',
                'destination': {'branch': {'name': 'development/1.0'},
                                 'commit': {'hash': '68fe68c5d83a',
                                             'links': {'self': {
                                                 'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/commit/68fe68c5d83a'}}},
                                 'repository': {
                                     'full_name': 'test_owner/test_repo',
                                     'links': {'avatar': {
                                         'href': 'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                                                'html': {
                                                    'href': 'https://bitbucket.org/test_owner/test_repo'},
                                                'self': {
                                                    'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
                                     'name': 'test_repo',
                                     'type': 'repository',
                                     'uuid': '{49a4c5bf-6684-4102-9e82-f9016f691392}'}},
                'id': 1,
                'links': {'html': {
                    'href': 'https://bitbucket.org/test_owner/test_repo/pull-requests/4'},
                           'self': {
                               'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4'}},
                'merge_commit': None,
                'participants': [{'approved': True,
                                   'role': 'REVIEWER',
                                   'type': 'participant',
                                   'user': {
                                       'display_name': 'Jane Doe',
                                       'links': {'avatar': {
                                           'href': 'https://bitbucket.org/account/jane_doe/avatar/32/'},
                                                  'html': {
                                                      'href': 'https://bitbucket.org/jane_doe/'},
                                                  'self': {
                                                      'href': 'https://api.bitbucket.org/2.0/users/jane_doe'}},
                                       'type': 'user',
                                       'username': 'jane_doe',
                                       'uuid': '{cafc4547-3736-45d2-b9ff-e00ddae73adc}'}},
                                  {'approved': False,
                                   'role': 'PARTICIPANT',
                                   'type': 'participant',
                                   'user': {
                                       'display_name': 'John Doe',
                                       'links': {'avatar': {
                                           'href': 'https://bitbucket.org/account/john_doe/avatar/32/'},
                                                  'html': {
                                                      'href': 'https://bitbucket.org/john_doe/'},
                                                  'self': {
                                                      'href': 'https://api.bitbucket.org/2.0/users/john_doe'}},
                                       'type': 'user',
                                       'username': 'john_doe',
                                       'uuid': '{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}},
                                  {'approved': False,
                                   'role': 'PARTICIPANT',
                                   'type': 'participant',
                                   'user': {'display_name': 'Bert-E',
                                             'links': {'avatar': {
                                                 'href': 'https://bitbucket.org/account/test_user/avatar/32/'},
                                                        'html': {
                                                            'href': 'https://bitbucket.org/test_user/'},
                                                        'self': {
                                                            'href': 'https://api.bitbucket.org/2.0/users/test_user'}},
                                             'type': 'user',
                                             'username': 'test_user',
                                             'uuid': '{267dd264-e12c-47de-87e2-2fb726f4667e}'}},
                                  {'approved': True,
                                   'role': 'PARTICIPANT',
                                   'type': 'participant',
                                   'user': {'display_name': 'Johanna Doe',
                                             'links': {'avatar': {
                                                 'href': 'https://bitbucket.org/account/johanna_doe/avatar/32/'},
                                                        'html': {
                                                            'href': 'https://bitbucket.org/johanna_doe/'},
                                                        'self': {
                                                            'href': 'https://api.bitbucket.org/2.0/users/johanna_doe'}},
                                             'type': 'user',
                                             'username': 'johanna_doe',
                                             'uuid': '{76527410-6118-4c2a-a1e7-274355957f0e}'}},
                                  {'approved': False,
                                   'role': 'REVIEWER',
                                   'type': 'participant',
                                   'user': {
                                       'display_name': 'Jenny Doe',
                                       'links': {'avatar': {
                                           'href': 'https://bitbucket.org/account/jenny_doe/avatar/32/'},
                                                  'html': {
                                                      'href': 'https://bitbucket.org/jenny_doe/'},
                                                  'self': {
                                                      'href': 'https://api.bitbucket.org/2.0/users/jenny_doe'}},
                                       'type': 'user',
                                       'username': 'jenny_doe',
                                       'uuid': '{e8a5e80b-a64c-438f-86cb-788c0403a9a2}'}},
                                  {'approved': False,
                                   'role': 'REVIEWER',
                                   'type': 'participant',
                                   'user': {
                                       'display_name': 'Johnny Doe',
                                       'links': {'avatar': {
                                           'href': 'https://bitbucket.org/account/johnny_doe/avatar/32/'},
                                                  'html': {
                                                      'href': 'https://bitbucket.org/johnny_doe/'},
                                                  'self': {
                                                      'href': 'https://api.bitbucket.org/2.0/users/johnny_doe'}},
                                       'type': 'user',
                                       'username': 'johnny_doe',
                                       'uuid': '{234cbbb0-1570-42a0-871c-5a984e099a85}'}}],
                'reason': '',
                'reviewers': [{'display_name': 'Johnny Doe',
                                'links': {'avatar': {
                                    'href': 'https://bitbucket.org/account/johnny_doe/avatar/32/'},
                                           'html': {
                                               'href': 'https://bitbucket.org/johnny_doe/'},
                                           'self': {
                                               'href': 'https://api.bitbucket.org/2.0/users/johnny_doe'}},
                                'type': 'user',
                                'username': 'johnny_doe',
                                'uuid': '{234cbbb0-1570-42a0-871c-5a984e099a85}'},
                               {'display_name': 'Jenny Doe',
                                'links': {'avatar': {
                                    'href': 'https://bitbucket.org/account/jenny_doe/avatar/32/'},
                                           'html': {
                                               'href': 'https://bitbucket.org/jenny_doe/'},
                                           'self': {
                                               'href': 'https://api.bitbucket.org/2.0/users/jenny_doe'}},
                                'type': 'user',
                                'username': 'jenny_doe',
                                'uuid': '{e8a5e80b-a64c-438f-86cb-788c0403a9a2}'},
                               {'display_name': 'Jane Doe',
                                'links': {'avatar': {
                                    'href': 'https://bitbucket.org/account/jane_doe/avatar/32/'},
                                           'html': {
                                               'href': 'https://bitbucket.org/jane_doe/'},
                                           'self': {
                                               'href': 'https://api.bitbucket.org/2.0/users/jane_doe'}},
                                'type': 'user',
                                'username': 'jane_doe',
                                'uuid': '{cafc4547-3736-45d2-b9ff-e00ddae73adc}'}],
                'source': {'branch': {
                    'name': 'bugfix/RELENG-1966-allow-bitbucket-pipeline-to-deploy'},
                            'commit': {'hash': 'c59c4e15a738',
                                        'links': {'self': {
                                            'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/commit/c59c4e15a738'}}},
                            'repository': {
                                'full_name': 'test_owner/test_repo',
                                'links': {'avatar': {
                                    'href': 'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                                           'html': {
                                               'href': 'https://bitbucket.org/test_owner/test_repo'},
                                           'self': {
                                               'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
                                'name': 'test_repo',
                                'type': 'repository',
                                'uuid': '{49a4c5bf-6684-4102-9e82-f9016f691392}'}},
                'state': 'OPEN',
                'title': 'Bugfix/releng 1966 allow bitbucket pipeline to deploy',
                'type': 'pullrequest',
                'updated_on': '2016-07-30T14:17:11.959821+00:00'}

REPOSITORY = {'full_name': 'test_owner/test_repo',
              'is_private': True,
              'links': {'avatar': {
                  'href': 'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                         'html': {
                             'href': 'https://bitbucket.org/test_owner/test_repo'},
                         'self': {
                             'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
              'name': 'test_repo',
              'owner': {'display_name': 'test_owner',
                         'links': {'avatar': {
                             'href': 'https://bitbucket.org/account/test_owner/avatar/32/'},
                                    'html': {
                                        'href': 'https://bitbucket.org/test_owner/'},
                                    'self': {
                                        'href': 'https://api.bitbucket.org/2.0/teams/test_owner'}},
                         'type': 'team',
                         'username': 'test_owner',
                         'uuid': '{ae308896-bf88-4899-a729-be0b0bb567ee}'},
              'project': {'key': 'RELENG',
                           'links': {'avatar': {
                               'href': 'https://bitbucket.org/account/user/test_owner/projects/RELENG/avatar/32'},
                                      'html': {
                                          'href': 'https://bitbucket.org/account/user/test_owner/projects/RELENG'}},
                           'name': 'Release Engineering',
                           'type': 'project',
                           'uuid': '{b7f2f3a1-e702-4c66-bd54-9fcb060982b9}'},
              'scm': 'git',
              'type': 'repository',
              'uuid': '{49a4c5bf-6684-4102-9e82-f9016f691392}',
              'website': ''}
COMMENT_CREATED = {'actor': ACTOR,
                   'comment': COMMENT,
                   'pullrequest': PULL_REQUEST,
                   'repository': REPOSITORY}

COMMIT_STATUS_CREATED = {
  'commit_status': {
    'description': 'in progress...[repository: bert-e][branch: feature/RELENG-1560-git-transactions]',
    'links': {
      'commit': {
        'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e/commit/b97b433b41405f157c51ca1336c21583413b87f3'
      },
      'self': {
        'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e/commit/b97b433b41405f157c51ca1336c21583413b87f3/statuses/build/pre-merge'
      }
    },
    'url': 'https://pipeline.example.com/bert-e/#builders/14/builds/1',
    'created_on': '2016-09-20T08:38:05.255626+00:00',
    'repository': {
      'links': {
        'self': {
          'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e'
        },
        'html': {
          'href': 'https://bitbucket.org/test_owner/bert-e'
        },
        'avatar': {
          'href': 'https://bitbucket.org/test_owner/bert-e/avatar/32/'
        }
      },
      'type': 'repository',
      'name': 'bert-e',
      'full_name': 'test_owner/bert-e',
      'uuid': '{5ff810b5-328e-4b7e-a003-9e822fa87b58}'
    },
    'state': 'INPROGRESS',
    'key': 'pre-merge',
    'updated_on': '2016-09-20T08:38:05.255666+00:00',
    'type': 'build',
    'name': '(starting) build #154 on bert-e:feature/RELENG-1560-git-transactions '
  },
  'repository': {
    'scm': 'git',
    'website': '',
    'name': 'bert-e',
    'links': {
      'self': {
        'href': 'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e'
      },
      'html': {
        'href': 'https://bitbucket.org/test_owner/bert-e'
      },
      'avatar': {
        'href': 'https://bitbucket.org/test_owner/bert-e/avatar/32/'
      }
    },
    'project': {
      'links': {
        'self': {
          'href': 'https://api.bitbucket.org/2.0/teams/test_owner/projects/RELENG'
        },
        'html': {
          'href': 'https://bitbucket.org/account/user/test_owner/projects/RELENG'
        },
        'avatar': {
          'href': 'https://bitbucket.org/account/user/test_owner/projects/RELENG/avatar/32'
        }
      },
      'type': 'project',
      'name': 'Release Engineering',
      'key': 'RELENG',
      'uuid': '{b7f2f3a1-e702-4c66-bd54-9fcb060982b9}'
    },
    'full_name': 'test_owner/bert-e',
    'owner': {
      'username': 'test_owner',
      'type': 'team',
      'display_name': 'test_owner',
      'uuid': '{ae308896-bf88-4899-a729-be0b0bb567ee}',
      'links': {
        'self': {
          'href': 'https://api.bitbucket.org/2.0/teams/test_owner'
        },
        'html': {
          'href': 'https://bitbucket.org/test_owner/'
        },
        'avatar': {
          'href': 'https://bitbucket.org/account/test_owner/avatar/32/'
        }
      }
    },
    'type': 'repository',
    'is_private': True,
    'uuid': '{5ff810b5-328e-4b7e-a003-9e822fa87b58}'
  },
  'actor': {
    'username': 'eva',
    'type': 'user',
    'display_name': 'Eva',
    'uuid': '{38ec89b3-7097-4517-a474-a35d6e8e24d6}',
    'links': {
      'self': {
        'href': 'https://api.bitbucket.org/2.0/users/eva'
      },
      'html': {
        'href': 'https://bitbucket.org/eva/'
      },
      'avatar': {
        'href': 'https://bitbucket.org/account/eva/avatar/32/'
      }
    }
  }
}
