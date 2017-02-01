"""
Git host module
"""

from .base import NoSuchGitHost

_API_CLIENTS = {}


def api_client(class_name):
    """Decorator.

    Associate a service name to a client class to instanciate.
    """
    def wrap(cls):
        _API_CLIENTS[class_name] = cls
        return cls
    return wrap


def client_factory(service, *args, **kwargs):
    """Factory function.

    Given the `service` parameter, try to instanciate the associated class.

    Args:
        - service: the service name from which to instanciate the class.

    Returns: an instance of the client class from the requested service.

    Raises: NoSuchGitHost if the service has no client implementation.

    """
    if service in _API_CLIENTS:
        return _API_CLIENTS[service](*args, **kwargs)
    raise NoSuchGitHost("{} has not been implemented yet.".format(service))
