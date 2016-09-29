# README #

Scality's automated branch merging tool. Version 2.0.

### How to install? ###

```
#!bash
$ git clone git@bitbucket.org:scality/wall-e.git
$ cd wall-e
$ virtualenv venv
$ source venv/bin/activate
$ pip install flake8 jira==1.0.3 requests==2.9.1 six-1.10.0 Jinja2==2.7.1
```

### How do I ask Wall-E to merge a pull request? ###

```
#!bash
$ python python wall_e.py <pull_request_id> <wall_e_pasword>

$ python wall_e.py --help
usage: wall_e.py [-h] [--disable-queues] [--option CMD_LINE_OPTIONS]
                 [--username USERNAME] [--email EMAIL]
                 [--reference-git-repo REFERENCE_GIT_REPO] [--owner OWNER]
                 [--slug SLUG] [--settings SETTINGS] [--interactive]
                 [--no-comment] [-v] [--backtrace] [--quiet]
                 token password

Merges bitbucket pull requests.

positional arguments:
  token                 The ID of the pull request or sha1 ([12, 40]
                        characters) to analyse
  password              Wall-E's password [for Jira and Bitbucket]

optional arguments:
  -h, --help            show this help message and exit
  --disable-queues      Deactivate optimistic merge queue (legacy mode)
  --option CMD_LINE_OPTIONS, -o CMD_LINE_OPTIONS
                        Activate additional options
  --username USERNAME   Wall-E's username [for Jira and Bitbucket]
  --email EMAIL         Wall-E's email [for Jira and Bitbucket]
  --reference-git-repo REFERENCE_GIT_REPO
                        Reference to a local git repo to improve cloning
                        delay. If empty, a local clone will be created
  --owner OWNER         The owner of the repo (default: scality)
  --slug SLUG           The repo's slug (default: ring)
  --settings SETTINGS   The settings to use (default to repository slug)
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
$ python test_wall_e.py <wall_e_password> <eva_password> \
                        <your_login> <your_password> <your.email@scality.com>
.......
----------------------------------------------------------------------
Ran 7 tests in 254.984s

OK

$ python test_wall_e.py --help
usage: test_wall_e.py [-h] [--repo-prefix REPO_PREFIX] [-v] [--failfast]
                      [--disable-mock]
                      wall_e_password eva_password your_login your_password
                      your_mail [tests [tests ...]]

Launches Wall-E tests.

positional arguments:
  wall_e_password       Wall-E's password [for Jira and Bitbucket]
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

### How to Launch Static Checker File?

```
$ flake8 *.py
```

