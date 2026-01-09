"""Production configuration/vault tests; no claim of a hosted or PostgreSQL run."""
import base64
import secrets

import pytest
from cryptography.fernet import Fernet,InvalidToken

from followdesk import create_app,vault,crm


def production(**overrides):
    settings=dict(TESTING=True,PRODUCTION=True,DATABASE_URL="postgresql://unused.invalid/never_connected",SECRET_KEY=secrets.token_hex(32),VAULT_KEY=Fernet.generate_key().decode(),TRUSTED_HOSTS=["follow.example"],LOOPDESK_URL="https://crm.example")
    settings.update(overrides)
    return create_app(settings)


def test_real_production_vault_and_secure_https_response(tmp_path):
    app=production(LOCAL_VAULT_FILE=str(tmp_path/"must-not-be-created"))
    with app.app_context():
        token="fictional-grant-for-production-vault-tests"
        first,second=vault.seal(token),vault.seal(token)
        assert first.startswith("fernet:") and first!=second and token not in first
        assert vault.open_token(first)==vault.open_token(second)==token
    assert not list(tmp_path.iterdir())
    response=app.test_client().get("/",base_url="https://follow.example")
    assert response.status_code==200
    cookie=response.headers["Set-Cookie"]
    assert all(value in cookie for value in ("Secure","HttpOnly","SameSite=Lax"))
    assert response.headers["Strict-Transport-Security"]=="max-age=31536000"
    assert response.headers["Cache-Control"]=="no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_production_vault_rejects_tampering_and_wrong_key():
    app=production()
    with app.app_context():
        encrypted=vault.seal("fictional-grant")
        raw=bytearray(base64.urlsafe_b64decode(encrypted[7:]))
        raw[40]^=1
        with pytest.raises(InvalidToken):vault.open_token("fernet:"+base64.urlsafe_b64encode(raw).decode())
        app.config["VAULT_KEY"]=Fernet.generate_key().decode()
        with pytest.raises(InvalidToken):vault.open_token(encrypted)


def test_production_vault_never_uses_local_fallback(monkeypatch):
    def forbidden(*args):raise AssertionError("Local crypto fallback used in production")
    monkeypatch.setattr(vault,"_local",forbidden)
    app=production()
    with app.app_context():
        with pytest.raises(RuntimeError,match="Cannot decrypt"):
            vault.open_token("aesgcm:local-ciphertext")
        app.config["VAULT_KEY"]=None
        with pytest.raises(RuntimeError,match="Configure FOLLOWDESK_VAULT_KEY"):
            vault.seal("fictional-grant")


@pytest.mark.parametrize("key",[None,"not-a-fernet-key","a"*44])
def test_production_requires_valid_vault_key(key):
    with pytest.raises((RuntimeError,ValueError)):
        production(VAULT_KEY=key)


@pytest.mark.parametrize("settings",[
    {"DATABASE_URL":"sqlite:///ignored.sqlite3"},
    {"SECRET_KEY":"replace-with-a-random-secret-of-at-least-32-characters"},
    {"TRUSTED_HOSTS":[]},
    {"LOOPDESK_URL":"http://127.0.0.1:5055"},
])
def test_production_rejects_unsafe_configuration(settings):
    with pytest.raises((RuntimeError,crm.CRMError)):
        production(**settings)


@pytest.mark.parametrize("origin",["https://","https://:443","https://crm.example:70000","https://crm.example:0","https://crm.example\n.evil.example",None])
def test_invalid_crm_origin_fails_at_configuration(origin):
    with pytest.raises(crm.CRMError):
        production(LOOPDESK_URL=origin)
