"""
Git host client factory module.

The client factory uses a dispatcher pattern to ease registration of new git
host APIs.

To register a new git host API implementation to this factory, simply decorate
the client class with @api_client(api_name).

Example:

    # bert_e.git_host.bitbucket module

    from bert_e.git_host import base, factory

    @factory.api_client('github')
    class GitHubClient(base.AbstractClient):
        # ... implementation of the client.

Additionnally, if you want the API to be automatically registered when loading
the git_host package, add it to the imports of the git_host.__init__ module.

"""

from .base import AbstractClient, NoSuchGitHost

_API_CLIENTS = {}


def api_client(api_name):
    """Decorator. Register a git host API client to the factory."""
    def wrap(cls):
        assert api_name not in _API_CLIENTS
        assert issubclass(cls, AbstractClient)
        _API_CLIENTS[api_name] = cls
        cls.git_provider = api_name
        return cls
    return wrap


def client_factory(service: str, *args, **kwargs) -> AbstractClient:
    """Factory function.

    Given the `service` parameter, instanciate the associated class.

    Args:
        - service: the service name from which to instanciate the class.

    Returns: an instance of the client class from the requested service.

    Raises: NoSuchGitHost if the service has no client implementation.

    """
    if service in _API_CLIENTS:
        return _API_CLIENTS[service](*args, **kwargs)
    raise NoSuchGitHost("{} has not been implemented yet.".format(service))
