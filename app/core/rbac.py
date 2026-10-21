from app.core.errors import forbidden
from app.models import User


def require_roles(actor: User, *roles: str) -> None:
    if not actor.is_active or actor.role not in roles:
        raise forbidden()
