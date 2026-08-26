# README

[![codecov](https://codecov.io/gh/scality/bert-e/graph/badge.svg?token=VWEQLKMUN5)](https://codecov.io/gh/scality/bert-e)

Scality's automated branch merging tool.

## User documentation

User documentation can be found [here](./bert_e/docs/USER_DOC.md)

## API documentation

API documentation can be found [here](./bert_e/docs/API_DOC.md)

## Develop on Bert-E

A codespace environment has been setup to develop on Bert-E.
It is the only supported method to develop on Bert-E.

All above instructions will assume you are inside the codespace environment

### Run the bot locally

```shell
$ cp settings.sample.yml settings.yml
# Configure settings.yml to your liking
$ tox run -e run
```

### Run local tests

A series of test scenario will be executed locally using mocks.

```shell
$ tox -e tests
```

### Run tests against githost

This step will run the same tests as above but instead
of using mocks to interact with a githost, it will interact
with the one you have configured.

Credentials are required to run this step, checkout [`tox.ini`](./tox.ini)
file for more details about which credentials are required.

### Extra commands

Checkout the [`tox.ini`](./tox.ini) for all available commands to develop with
bert-e.

## Contributing a new check

Every new check that blocks a merge **must** ship with a corresponding
`bypass_<check_name>` privileged option. This is a hard requirement — without
a bypass, a false positive permanently blocks a legitimate PR with no
administrator escape hatch.

Checklist for a new check:

1. Add `bypass_<check_name>(job)` to `bert_e/workflow/gitwaterflow/utils.py`
2. Register the option in `commands.py` `setup()` with `privileged=True`
3. Import and call `bypass_<check_name>(job)` at the top of the check function
4. Mention the bypass in the error message template
5. Document the check and bypass in `bert_e/docs/USER_DOC.md`
6. Add a unit test that verifies the bypass skips the check
