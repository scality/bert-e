from gettext import install
from bert_e.git_host.github import Client
from pytest import fixture
from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend as crypto_default_backend

@fixture
def client_app():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=crypto_default_backend()
    )
    return Client(
        login='login',
        password='password',
        email='email@org.com',
        app_id=1,
        installation_id=1,
        private_key=private_key.private_bytes(
            crypto_serialization.Encoding.PEM,
            crypto_serialization.PrivateFormat.PKCS8,
            crypto_serialization.NoEncryption()
        ),
        base_url="http://localhost:4010",
        accept_header="application/json"
    )

def test_github_auth_app(client_app):
    repository = client_app.get_repository('octo-org', 'Hello-World')
    pr = repository.get_pull_request(1)
    assert pr.id == 1347
    assert client_app.headers['Authorization'].startswith('Bearer ') == True
