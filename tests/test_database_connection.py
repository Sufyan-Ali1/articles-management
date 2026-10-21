import ssl

import pytest

from app.db.connection import connection_options


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_provider_tls_options(mode: str) -> None:
    url, arguments = connection_options(
        f"postgresql+asyncpg://user:password@db.example/blog?sslmode={mode}&channel_binding=require"
    )
    assert not url.query
    context = arguments["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert url.password == "password"


def test_local_url_preserved() -> None:
    url, arguments = connection_options("postgresql+asyncpg://localhost/blog")
    assert url.host == "localhost"
    assert arguments == {}


def test_channel_binding_without_tls_rejected() -> None:
    with pytest.raises(ValueError, match="verified TLS"):
        connection_options("postgresql+asyncpg://localhost/blog?channel_binding=require")
