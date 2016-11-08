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
$ python python bert_e.py <pull_request_id> <bert_e_pasword>

$ python bert_e.py --help
usage: bert_e.py [-h] [--disable-queues] [--option CMD_LINE_OPTIONS]
                 [--username USERNAME] [--email EMAIL]
                 [--reference-git-repo REFERENCE_GIT_REPO] [--owner OWNER]
                 [--slug SLUG] [--settings SETTINGS] [--interactive]
                 [--no-comment] [-v] [--backtrace] [--quiet]
                 token password

Merges bitbucket pull requests.

positional arguments:
  token                 The ID of the pull request or sha1 ([12, 40]
                        characters) to analyse
  password              Bert-E's password [for Jira and Bitbucket]

optional arguments:
  -h, --help            show this help message and exit
  --disable-queues      Deactivate optimistic merge queue (legacy mode)
  --option CMD_LINE_OPTIONS, -o CMD_LINE_OPTIONS
                        Activate additional options
  --username USERNAME   Bert-E's username [for Jira and Bitbucket]
  --email EMAIL         Bert-E's email [for Jira and Bitbucket]
  --reference-git-repo REFERENCE_GIT_REPO
                        Reference to a local git repo to improve cloning
                        delay. If empty, a local clone will be created
  --owner OWNER         The owner of the repo (default: scality)
  --slug SLUG           The repo's slug (default: ring)
  --settings SETTINGS   Path to project settings file
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
$ python test_bert_e.py <bert_e_password> <eva_password> \
                        <your_login> <your_password> <your.email@scality.com>
.......
----------------------------------------------------------------------
Ran 7 tests in 254.984s

OK

$ python test_bert_e.py --help
usage: test_bert_e.py [-h] [--repo-prefix REPO_PREFIX] [-v] [--failfast]
                      [--disable-mock]
                      bert_e_password eva_password your_login your_password
                      your_mail [tests [tests ...]]

Launches Bert-E tests.

positional arguments:
  bert_e_password       Bert-E's password [for Jira and Bitbucket]
  eva_password          Eva's password [for Jira and Bitbucket]
  your_login            Your Bitbucket login
  your_password         Your Bitbucket password
  your_mail             Your Bitbucket email address
  tests                 run only these tests

optional arguments:
  -h, --help            show this help message and exit
  --repo-prefix REPO_PREFIX
                        Prefix of the test repository
  -v                    Verbose mode
  --failfast            Return on first failure
  --disable-mock        Disables the bitbucket mock (slower tests)
```

### How do I launch the standalone webhook listener (server.py) ?

First you have to export the following environment variables:

* `BERT_E_PWD` Bert-E's password on Bitbucket.
* `WEBHOOK_LOGIN`, `WEBHOOK_PWD` The HTTP BasicAuth credentials used to
  authenticate the requests sent to server.py by Bitbucket.


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

