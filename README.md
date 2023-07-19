# README

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
$ tox -e run
```

### Run local tests

A series of test scenario will be executed locally using mocks.

```shell
$ tox run -e tests
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
