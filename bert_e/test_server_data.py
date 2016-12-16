# flake8: noqa

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

ACTOR = {u'display_name': u'John Doe',
         u'links': {u'avatar': {
             u'href': u'https://bitbucket.org/account/john_doe/avatar/32/'},
                    u'html': {
                        u'href': u'https://bitbucket.org/john_doe/'},
                    u'self': {
                        u'href': u'https://api.bitbucket.org/2.0/users/john_doe'}},
         u'type': u'user',
         u'username': u'john_doe',
         u'uuid': u'{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}

COMMENT = {u'content': {u'html': u'<p>test16</p>',
                        u'markup': u'markdown',
                        u'raw': u'test16'},
           u'created_on': u'2016-07-30T14:17:11.953311+00:00',
           u'id': 21710334,
           u'links': {u'html': {
               u'href': u'https://bitbucket.org/test_owner/test_repo/pull-requests/4/_/diff#comment-21710334'},
                      u'self': {
                          u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4/comments/21710334'}},
           u'parent': {u'id': 21710326,
                       u'links': {u'html': {
                           u'href': u'https://bitbucket.org/test_owner/test_repo/pull-requests/4/_/diff#comment-21710326'},
                                  u'self': {
                                      u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4/comments/21710326'}}},
           u'pullrequest': {u'id': 1,
                            u'links': {u'html': {
                                u'href': u'https://bitbucket.org/test_owner/test_repo/pull-requests/4'},
                                       u'self': {
                                           u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4'}},
                            u'title': u'Bugfix/releng 1966 allow bitbucket pipeline to deploy',
                            u'type': u'pullrequest'},
           u'type': u'pullrequest_comment',
           u'updated_on': u'2016-07-30T14:17:11.954715+00:00',
           u'user': {u'display_name': u'John Doe',
                     u'links': {u'avatar': {
                         u'href': u'https://bitbucket.org/account/john_doe/avatar/32/'},
                                u'html': {
                                    u'href': u'https://bitbucket.org/john_doe/'},
                                u'self': {
                                    u'href': u'https://api.bitbucket.org/2.0/users/john_doe'}},
                     u'type': u'user',
                     u'username': u'john_doe',
                     u'uuid': u'{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}}

PULL_REQUEST = {u'author': {u'display_name': u'Johanna Doe',
                            u'links': {u'avatar': {
                                u'href': u'https://bitbucket.org/account/johanna_doe/avatar/32/'},
                                       u'html': {
                                           u'href': u'https://bitbucket.org/johanna_doe/'},
                                       u'self': {
                                           u'href': u'https://api.bitbucket.org/2.0/users/johanna_doe'}},
                            u'type': u'user',
                            u'username': u'johanna_doe',
                            u'uuid': u'{76527410-6118-4c2a-a1e7-274355957f0e}'},
                u'close_source_branch': True,
                u'closed_by': None,
                u'comment_count': 11,
                u'created_on': u'2016-07-29T12:20:33.873540+00:00',
                u'description': u'* Add HTTP basic auth as fallback to IP whitelisting\r\n\r\n* Fix htpasswd encoding of ssha',
                u'destination': {u'branch': {u'name': u'development/1.0'},
                                 u'commit': {u'hash': u'68fe68c5d83a',
                                             u'links': {u'self': {
                                                 u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/commit/68fe68c5d83a'}}},
                                 u'repository': {
                                     u'full_name': u'test_owner/test_repo',
                                     u'links': {u'avatar': {
                                         u'href': u'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                                                u'html': {
                                                    u'href': u'https://bitbucket.org/test_owner/test_repo'},
                                                u'self': {
                                                    u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
                                     u'name': u'test_repo',
                                     u'type': u'repository',
                                     u'uuid': u'{49a4c5bf-6684-4102-9e82-f9016f691392}'}},
                u'id': 1,
                u'links': {u'html': {
                    u'href': u'https://bitbucket.org/test_owner/test_repo/pull-requests/4'},
                           u'self': {
                               u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/pullrequests/4'}},
                u'merge_commit': None,
                u'participants': [{u'approved': True,
                                   u'role': u'REVIEWER',
                                   u'type': u'participant',
                                   u'user': {
                                       u'display_name': u'Jane Doe',
                                       u'links': {u'avatar': {
                                           u'href': u'https://bitbucket.org/account/jane_doe/avatar/32/'},
                                                  u'html': {
                                                      u'href': u'https://bitbucket.org/jane_doe/'},
                                                  u'self': {
                                                      u'href': u'https://api.bitbucket.org/2.0/users/jane_doe'}},
                                       u'type': u'user',
                                       u'username': u'jane_doe',
                                       u'uuid': u'{cafc4547-3736-45d2-b9ff-e00ddae73adc}'}},
                                  {u'approved': False,
                                   u'role': u'PARTICIPANT',
                                   u'type': u'participant',
                                   u'user': {
                                       u'display_name': u'John Doe',
                                       u'links': {u'avatar': {
                                           u'href': u'https://bitbucket.org/account/john_doe/avatar/32/'},
                                                  u'html': {
                                                      u'href': u'https://bitbucket.org/john_doe/'},
                                                  u'self': {
                                                      u'href': u'https://api.bitbucket.org/2.0/users/john_doe'}},
                                       u'type': u'user',
                                       u'username': u'john_doe',
                                       u'uuid': u'{ccd8a297-9f6d-40c2-bc3b-5639ee18c7fa}'}},
                                  {u'approved': False,
                                   u'role': u'PARTICIPANT',
                                   u'type': u'participant',
                                   u'user': {u'display_name': u'Bert-E',
                                             u'links': {u'avatar': {
                                                 u'href': u'https://bitbucket.org/account/test_user/avatar/32/'},
                                                        u'html': {
                                                            u'href': u'https://bitbucket.org/test_user/'},
                                                        u'self': {
                                                            u'href': u'https://api.bitbucket.org/2.0/users/test_user'}},
                                             u'type': u'user',
                                             u'username': u'test_user',
                                             u'uuid': u'{267dd264-e12c-47de-87e2-2fb726f4667e}'}},
                                  {u'approved': True,
                                   u'role': u'PARTICIPANT',
                                   u'type': u'participant',
                                   u'user': {u'display_name': u'Johanna Doe',
                                             u'links': {u'avatar': {
                                                 u'href': u'https://bitbucket.org/account/johanna_doe/avatar/32/'},
                                                        u'html': {
                                                            u'href': u'https://bitbucket.org/johanna_doe/'},
                                                        u'self': {
                                                            u'href': u'https://api.bitbucket.org/2.0/users/johanna_doe'}},
                                             u'type': u'user',
                                             u'username': u'johanna_doe',
                                             u'uuid': u'{76527410-6118-4c2a-a1e7-274355957f0e}'}},
                                  {u'approved': False,
                                   u'role': u'REVIEWER',
                                   u'type': u'participant',
                                   u'user': {
                                       u'display_name': u'Jenny Doe',
                                       u'links': {u'avatar': {
                                           u'href': u'https://bitbucket.org/account/jenny_doe/avatar/32/'},
                                                  u'html': {
                                                      u'href': u'https://bitbucket.org/jenny_doe/'},
                                                  u'self': {
                                                      u'href': u'https://api.bitbucket.org/2.0/users/jenny_doe'}},
                                       u'type': u'user',
                                       u'username': u'jenny_doe',
                                       u'uuid': u'{e8a5e80b-a64c-438f-86cb-788c0403a9a2}'}},
                                  {u'approved': False,
                                   u'role': u'REVIEWER',
                                   u'type': u'participant',
                                   u'user': {
                                       u'display_name': u'Johnny Doe',
                                       u'links': {u'avatar': {
                                           u'href': u'https://bitbucket.org/account/johnny_doe/avatar/32/'},
                                                  u'html': {
                                                      u'href': u'https://bitbucket.org/johnny_doe/'},
                                                  u'self': {
                                                      u'href': u'https://api.bitbucket.org/2.0/users/johnny_doe'}},
                                       u'type': u'user',
                                       u'username': u'johnny_doe',
                                       u'uuid': u'{234cbbb0-1570-42a0-871c-5a984e099a85}'}}],
                u'reason': u'',
                u'reviewers': [{u'display_name': u'Johnny Doe',
                                u'links': {u'avatar': {
                                    u'href': u'https://bitbucket.org/account/johnny_doe/avatar/32/'},
                                           u'html': {
                                               u'href': u'https://bitbucket.org/johnny_doe/'},
                                           u'self': {
                                               u'href': u'https://api.bitbucket.org/2.0/users/johnny_doe'}},
                                u'type': u'user',
                                u'username': u'johnny_doe',
                                u'uuid': u'{234cbbb0-1570-42a0-871c-5a984e099a85}'},
                               {u'display_name': u'Jenny Doe',
                                u'links': {u'avatar': {
                                    u'href': u'https://bitbucket.org/account/jenny_doe/avatar/32/'},
                                           u'html': {
                                               u'href': u'https://bitbucket.org/jenny_doe/'},
                                           u'self': {
                                               u'href': u'https://api.bitbucket.org/2.0/users/jenny_doe'}},
                                u'type': u'user',
                                u'username': u'jenny_doe',
                                u'uuid': u'{e8a5e80b-a64c-438f-86cb-788c0403a9a2}'},
                               {u'display_name': u'Jane Doe',
                                u'links': {u'avatar': {
                                    u'href': u'https://bitbucket.org/account/jane_doe/avatar/32/'},
                                           u'html': {
                                               u'href': u'https://bitbucket.org/jane_doe/'},
                                           u'self': {
                                               u'href': u'https://api.bitbucket.org/2.0/users/jane_doe'}},
                                u'type': u'user',
                                u'username': u'jane_doe',
                                u'uuid': u'{cafc4547-3736-45d2-b9ff-e00ddae73adc}'}],
                u'source': {u'branch': {
                    u'name': u'bugfix/RELENG-1966-allow-bitbucket-pipeline-to-deploy'},
                            u'commit': {u'hash': u'c59c4e15a738',
                                        u'links': {u'self': {
                                            u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo/commit/c59c4e15a738'}}},
                            u'repository': {
                                u'full_name': u'test_owner/test_repo',
                                u'links': {u'avatar': {
                                    u'href': u'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                                           u'html': {
                                               u'href': u'https://bitbucket.org/test_owner/test_repo'},
                                           u'self': {
                                               u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
                                u'name': u'test_repo',
                                u'type': u'repository',
                                u'uuid': u'{49a4c5bf-6684-4102-9e82-f9016f691392}'}},
                u'state': u'OPEN',
                u'task_count': 0,
                u'title': u'Bugfix/releng 1966 allow bitbucket pipeline to deploy',
                u'type': u'pullrequest',
                u'updated_on': u'2016-07-30T14:17:11.959821+00:00'}

REPOSITORY = {u'full_name': u'test_owner/test_repo',
              u'is_private': True,
              u'links': {u'avatar': {
                  u'href': u'https://bitbucket.org/test_owner/test_repo/avatar/32/'},
                         u'html': {
                             u'href': u'https://bitbucket.org/test_owner/test_repo'},
                         u'self': {
                             u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/test_repo'}},
              u'name': u'test_repo',
              u'owner': {u'display_name': u'test_owner',
                         u'links': {u'avatar': {
                             u'href': u'https://bitbucket.org/account/test_owner/avatar/32/'},
                                    u'html': {
                                        u'href': u'https://bitbucket.org/test_owner/'},
                                    u'self': {
                                        u'href': u'https://api.bitbucket.org/2.0/teams/test_owner'}},
                         u'type': u'team',
                         u'username': u'test_owner',
                         u'uuid': u'{ae308896-bf88-4899-a729-be0b0bb567ee}'},
              u'project': {u'key': u'RELENG',
                           u'links': {u'avatar': {
                               u'href': u'https://bitbucket.org/account/user/test_owner/projects/RELENG/avatar/32'},
                                      u'html': {
                                          u'href': u'https://bitbucket.org/account/user/test_owner/projects/RELENG'}},
                           u'name': u'Release Engineering',
                           u'type': u'project',
                           u'uuid': u'{b7f2f3a1-e702-4c66-bd54-9fcb060982b9}'},
              u'scm': u'git',
              u'type': u'repository',
              u'uuid': u'{49a4c5bf-6684-4102-9e82-f9016f691392}',
              u'website': u''}
COMMENT_CREATED = {u'actor': ACTOR,
                   u'comment': COMMENT,
                   u'pullrequest': PULL_REQUEST,
                   u'repository': REPOSITORY}

COMMIT_STATUS_CREATED = {
  u'commit_status': {
    u'description': u'in progress...[repository: bert-e][branch: feature/RELENG-1560-git-transactions]',
    u'links': {
      u'commit': {
        u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e/commit/b97b433b41405f157c51ca1336c21583413b87f3'
      },
      u'self': {
        u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e/commit/b97b433b41405f157c51ca1336c21583413b87f3/statuses/build/pre-merge'
      }
    },
    u'url': u'https://pipeline.example.com/bert-e/#builders/14/builds/1',
    u'created_on': u'2016-09-20T08:38:05.255626+00:00',
    u'repository': {
      u'links': {
        u'self': {
          u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e'
        },
        u'html': {
          u'href': u'https://bitbucket.org/test_owner/bert-e'
        },
        u'avatar': {
          u'href': u'https://bitbucket.org/test_owner/bert-e/avatar/32/'
        }
      },
      u'type': u'repository',
      u'name': u'bert-e',
      u'full_name': u'test_owner/bert-e',
      u'uuid': u'{5ff810b5-328e-4b7e-a003-9e822fa87b58}'
    },
    u'state': u'INPROGRESS',
    u'key': u'pre-merge',
    u'updated_on': u'2016-09-20T08:38:05.255666+00:00',
    u'type': u'build',
    u'name': u'(starting) build #154 on bert-e:feature/RELENG-1560-git-transactions '
  },
  u'repository': {
    u'scm': u'git',
    u'website': u'',
    u'name': u'bert-e',
    u'links': {
      u'self': {
        u'href': u'https://api.bitbucket.org/2.0/repositories/test_owner/bert-e'
      },
      u'html': {
        u'href': u'https://bitbucket.org/test_owner/bert-e'
      },
      u'avatar': {
        u'href': u'https://bitbucket.org/test_owner/bert-e/avatar/32/'
      }
    },
    u'project': {
      u'links': {
        u'self': {
          u'href': u'https://api.bitbucket.org/2.0/teams/test_owner/projects/RELENG'
        },
        u'html': {
          u'href': u'https://bitbucket.org/account/user/test_owner/projects/RELENG'
        },
        u'avatar': {
          u'href': u'https://bitbucket.org/account/user/test_owner/projects/RELENG/avatar/32'
        }
      },
      u'type': u'project',
      u'name': u'Release Engineering',
      u'key': u'RELENG',
      u'uuid': u'{b7f2f3a1-e702-4c66-bd54-9fcb060982b9}'
    },
    u'full_name': u'test_owner/bert-e',
    u'owner': {
      u'username': u'test_owner',
      u'type': u'team',
      u'display_name': u'test_owner',
      u'uuid': u'{ae308896-bf88-4899-a729-be0b0bb567ee}',
      u'links': {
        u'self': {
          u'href': u'https://api.bitbucket.org/2.0/teams/test_owner'
        },
        u'html': {
          u'href': u'https://bitbucket.org/test_owner/'
        },
        u'avatar': {
          u'href': u'https://bitbucket.org/account/test_owner/avatar/32/'
        }
      }
    },
    u'type': u'repository',
    u'is_private': True,
    u'uuid': u'{5ff810b5-328e-4b7e-a003-9e822fa87b58}'
  },
  u'actor': {
    u'username': u'eva',
    u'type': u'user',
    u'display_name': u'Eva',
    u'uuid': u'{38ec89b3-7097-4517-a474-a35d6e8e24d6}',
    u'links': {
      u'self': {
        u'href': u'https://api.bitbucket.org/2.0/users/eva'
      },
      u'html': {
        u'href': u'https://bitbucket.org/eva/'
      },
      u'avatar': {
        u'href': u'https://bitbucket.org/account/eva/avatar/32/'
      }
    }
  }
}
