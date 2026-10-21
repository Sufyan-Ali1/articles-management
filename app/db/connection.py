import logging
import ssl
from typing import Any

import certifi
from sqlalchemy.engine import URL, make_url


def connection_options(database_url: str) -> tuple[URL, dict[str, Any]]:
    """Translate provider URL options to SQLAlchemy's asyncpg arguments."""
    url = make_url(database_url)
    mode = url.query.get("sslmode", url.query.get("ssl"))
    binding = url.query.get("channel_binding")
    if binding is not None:
        if mode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("channel_binding URL options require verified TLS")
        logging.getLogger(__name__).warning(
            "database.channel_binding_unsupported_using_verified_tls"
        )
    url = url.difference_update_query(["sslmode", "ssl", "channel_binding"])
    arguments: dict[str, Any] = {}
    if mode in {"require", "verify-ca", "verify-full"}:
        # Managed databases use publicly trusted certificates. Verify both the
        # certificate chain and hostname, including when the URL only says require.
        arguments["ssl"] = ssl.create_default_context(cafile=certifi.where())
    elif mode is not None:
        if mode not in {"disable", "allow", "prefer"}:
            raise ValueError("Unsupported database TLS mode")
        arguments["ssl"] = mode
    return url, arguments
