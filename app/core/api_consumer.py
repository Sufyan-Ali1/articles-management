import secrets

from app.core.config import Settings


def valid_api_consumer(settings: Settings, user: str | None, key: str | None) -> bool:
    if not settings.api_user or not settings.api_key or user is None or key is None:
        return False
    user_matches = secrets.compare_digest(
        user.encode(), settings.api_user.get_secret_value().encode()
    )
    key_matches = secrets.compare_digest(key.encode(), settings.api_key.get_secret_value().encode())
    return user_matches and key_matches
