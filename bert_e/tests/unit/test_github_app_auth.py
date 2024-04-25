from bert_e.git_host.github import Client
from pytest import fixture
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


@fixture
def client_app():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    return Client(
        login='login',
        password='password',
        email='email@org.com',
        app_id=1,
        installation_id=1,
        private_key=private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        ),
        base_url="http://localhost:4010",
        accept_header="application/json"
    )


def test_github_auth_app(client_app):
    repository = client_app.get_repository('octo-org', 'Hello-World')
    pr = repository.get_pull_request(1)
    assert pr.id == 1347
    assert client_app.headers['Authorization'].startswith('Bearer ') is True


def test_github_check_run(client_app):
    repository = client_app.get_repository('octo-org', 'Hello-World')
    pr = repository.get_pull_request(1)
    check_run = pr._add_checkrun(
        'bert-e', 'completed', 'success', 'title', 'summary')
    assert check_run.name == check_run.data['name']


def test_github_set_status(client_app):
    repository = client_app.get_repository('octo-org', 'Hello-World')
    pr = repository.get_pull_request(1)
    pr.set_bot_status('success', 'title', 'summary')
