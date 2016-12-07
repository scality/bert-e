# README #

Scality's automated branch merging tool. Version 2.0.

### How to install? ###

```
#!bash
$ git clone git@bitbucket.org:scality/bert-e.git
$ cd bert-e
$ virtualenv venv
$ source venv/bin/activate
$ pip install flake8 jira==1.0.3 requests==2.9.1 six-1.10.0 Jinja2==2.7.1
```

### How do I ask Bert-E to merge a pull request? ###

```
#!bash
usage: bert_e.py [-h] [--disable-queues] [--option CMD_LINE_OPTIONS]
                 [--reference-git-repo REFERENCE_GIT_REPO] [--interactive]
                 [--no-comment] [-v] [--backtrace] [--quiet]
                 settings bitbucket_password jira_password token

Merges bitbucket pull requests.

positional arguments:
  settings              Path to project settings file
  bitbucket_password    Bert-E's Bitbucket account password
  jira_password         Bert-E's Jira account password
  token                 The ID of the pull request or sha1 ([12, 40]
                        characters) to analyse

optional arguments:
  -h, --help            show this help message and exit
  --disable-queues      Deactivate optimistic merge queue (legacy mode)
  --option CMD_LINE_OPTIONS, -o CMD_LINE_OPTIONS
                        Activate additional options
  --reference-git-repo REFERENCE_GIT_REPO
                        Reference to a local git repo to improve cloning
                        delay. If empty, a local clone will be created
  --interactive         Ask before merging or sending comments
  --no-comment          Do not add any comment to the pull request page
  -v                    Verbose mode
  --backtrace           Show backtrace instead of return code on console
  --quiet               Don't print return codes on the console

```

### How to launch tests? ###

You should check that you have set a password to your bitbucket account.
If the text input `Old password` doesn't appear here:
`https://bitbucket.org/account/password/change/<your_login>/`, you must set a password.

```
#!bash
$ python test_bert_e.py <owner> \
                        <bert_e_username> <bert_e_password> \
                        <eva_username> <eva_password> \
                        <your_login> <your_password>
.............................................................s........
----------------------------------------------------------------------
Ran 103 tests in 152.139s

OK (skipped=2)


$ python test_bert_e.py --help
usage: test_bert_e.py [-h] [--repo-prefix REPO_PREFIX] [-v] [--failfast]
                      [--disable-mock] [--disable-queues]
                      owner bert_e_username bert_e_password eva_username
                      eva_password your_login your_password
                      [tests [tests ...]]

Launches Bert-E tests.

positional arguments:
  owner                 Owner of test repository (aka Bitbucket team)
  bert_e_username       Bert-E's username [for Jira and Bitbucket]
  bert_e_password       Bert-E's password [for Jira and Bitbucket]
  eva_username          Eva's username [for Bitbucket]
  eva_password          Eva's password [for Bitbucket]
  your_login            Your Bitbucket login
  your_password         Your Bitbucket password
  tests                 run only these tests

optional arguments:
  -h, --help            show this help message and exit
  --repo-prefix REPO_PREFIX
                        Prefix of the test repository
  -v                    Verbose mode
  --failfast            Return on first failure
  --disable-mock        Disables the bitbucket mock (slower tests)
  --disable-queues      deactivate queue feature during tests
```

### How do I launch the standalone webhook listener (server.py) ?

```
#!bash
usage: server.py [-h] [--host HOST] [--port PORT]
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

* `BERT_E_BB_PWD` Bert-E's password on Bitbucket.
* `BERT_E_JIRA_PWD` Bert-E's password on Jira.
* `WEBHOOK_LOGIN`, `WEBHOOK_PWD` The HTTP BasicAuth credentials used to
  authenticate the requests sent to server.py by Bitbucket.

Ensure settings-file contains configuration for the project you want
Bert-E to handle. A commented sample file is included (settings.sample.yml).
Place the template in a file called:

{settings_dir}/{owner}/{slug}

Then simply run:

```
$ python server.py --host 0.0.0.0 --port 8080
```

The server is now listening for webhooks on
`http://<webhook_login>:<webhook_pwd>@localhost:8080/bitbucket/`.

You can access the monitoring page without authentication on
`http://localhost:8080/`.


### How to Launch Static Checker File?

```
$ flake8 *.py
```

