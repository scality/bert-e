# README

Scality's automated branch merging tool.

### How to install?

Make sure you are using Python version 3.5 or above.

```bash
$ mkdir bert-e && cd bert-e
$ virtualenv venv
$ source venv/bin/activate
$ pip install git+ssh://git@bitbucket.org/scality/bert-e.git
```

### How do I launch the standalone webhook listener (server.py) ?

```bash
usage: bert-e-serve [-h] [--host HOST] [--port PORT]
                    [--settings-file SETTINGS_FILE] [--verbose]

Handles webhook calls.

optional arguments:
  -h, --help            show this help message and exit
  --host HOST           server host (defaults to 0.0.0.0)
  --port PORT, -p PORT  server port (defaults to 5000)
  --settings-file SETTINGS_FILE, -f SETTINGS_FILE
                        settings-file location
  --verbose, -v         verbose mode
```

First you have to export the following environment variables:

* `BERT_E_GITHOST_PWD` Bert-E's password on Bitbucket or Github.
* `BERT_E_JIRA_PWD` Bert-E's password on Jira.
* `WEBHOOK_LOGIN`, `WEBHOOK_PWD` The HTTP BasicAuth credentials used to
  authenticate the git host webhook requests.
* `BERT_E_CLIENT_ID`, `BERT_E_CLIENT_SECRET` the OAuth key
  used to authenticate users who want to login and access Bert-E's API.

Ensure settings-file contains configuration for the project you want
Bert-E to handle. A commented sample file is included (settings.sample.yml).
Place the template in a file called:

{settings_dir}/{owner}/{slug}

Then simply run:

```
$ bert-e-serve --host 0.0.0.0 --port 8080
```

The server is now listening for webhooks on
`http://<webhook_login>:<webhook_pwd>@localhost:8080/bitbucket/`.

You can access the monitoring page without authentication on
`http://localhost:8080/`.


### How to launch tests?

You should check that you have set a password to your bitbucket account.
If the text input `Old password` doesn't appear here:
`https://bitbucket.org/account/password/change/<your_login>/`, you must set a password.

```bash
$ python -m bert_e.tests.test_bert_e <owner> \
                                     <bert_e_username> <bert_e_password> \
                                     <eva_username> <eva_password> \
                                     <your_login> <your_password>
.............................................................s........
----------------------------------------------------------------------
Ran 103 tests in 152.139s

OK (skipped=2)


$ python -m bert_e.tests.test_bert_e --help
usage: test_bert_e.py [-h] [--repo-prefix REPO_PREFIX] [-v] [--failfast]
                      [--git-host GIT_HOST] [--disable-queues]
                      owner robot_username robot_password contributor_username
                      contributor_password admin_username admin_password
                      [tests [tests ...]]

Launches Bert-E tests.

positional arguments:
  owner                 Owner of test repository (aka Bitbucket/GitHub team)
  robot_username        Robot Bitbucket/GitHub username
  robot_password        Robot Bitbucket/GitHub password
  contributor_username  Contributor Bitbucket/GitHub username
  contributor_password  Contributor Bitbucket/GitHub password
  admin_username        Privileged user Bitbucket/GitHub username
  admin_password        Privileged user Bitbucket/GitHub password
  tests                 run only these tests

optional arguments:
  -h, --help            show this help message and exit
  --repo-prefix REPO_PREFIX
                        Prefix of the test repository
  -v                    Verbose mode
  --failfast            Return on first failure
  --git-host GIT_HOST   Choose the git host to run tests (slower tests)
  --disable-queues      deactivate queue feature during tests
```

### How to Launch Static Checker File?

```
$ flake8 bert-e/
```
