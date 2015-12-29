# README #

Scality's automated branch merging tool

### How to install? ###

```
#!bash
$ git clone git@bitbucket.org:scality/wall-e.git
$ cd wall-e
$ virtualenv venv
$ source venv/bin/activate
$ pip install flake8
$ pip install pybitbucket==0.8.0
$ pip install Jinja2==2.8

```

### How to Launch Static Checker File?

```
$ flake8 *.py
```

### How to launch tests? ###

You should check that you have set a password to your bitbucket account.
If the text input `Old password` doesn't appear here:
`https://bitbucket.org/account/password/change/<your_login>/`, you must set a password.

```
#!bash
$ python test_wall_e.py <wall_e_password> <your_login> <your_password> <your.email@scality.com> 
.......
----------------------------------------------------------------------
Ran 7 tests in 254.984s

OK

$ python test_wall_e.py --help
usage: test_wall_e.py [-h] wall_e_password your_login your_password your_mail

Launches Wall-E tests.

positional arguments:
  wall_e_password  Wall-E\'s password [for Jira and Bitbucket]
  your_login       Your Bitbucket login
  your_password    Your Bitbucket password
  your_mail        Your Bitbucket email address

optional arguments:
  -h, --help       show this help message and exit
```

### How do I ask Wall-E to merge a pull request? ###

```
#!bash
$ python python wall_e.py <pull_request_id> <wall_e_pasword>

$ python wall_e.py --help
usage: wall_e.py [-h] [--owner OWNER] [--slug SLUG] [--bypass_author_approval]
                 [--bypass_peer_approval]
                 [--reference_git_repo REFERENCE_GIT_REPO]
                 pullrequest password

Merges bitbucket pull requests.

positional arguments:
  pullrequest           The ID of the pull request
  password              Wall-E\'s password [for Jira and Bitbucket]

optional arguments:
  -h, --help            show this help message and exit
  --owner OWNER         The owner of the repo (default: scality)
  --slug SLUG           The repo\'s slug (default: ring)
  --bypass_author_approval
                        Bypass the pull request author\'s approval
  --bypass_peer_approval
                        Bypass the pull request peer\'s approval
  --reference_git_repo REFERENCE_GIT_REPO
                        Reference to a local version of the git repo to
                        improve cloning delay
```
