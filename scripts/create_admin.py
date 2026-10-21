import asyncio
import getpass

from pydantic import ValidationError
from sqlalchemy import exists, select

from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import hash_password
from app.db.session import create_database
from app.models import AdminLog, User
from app.schemas.users import UserCreate
from app.services.common import advisory_lock, transaction
from app.services.users import ADMIN_LOCK


async def bootstrap(data: UserCreate) -> None:
    engine, factory = create_database(get_settings())
    try:
        encoded = await hash_password(data.password.get_secret_value())
        async with factory() as session, transaction(session):
            await advisory_lock(session, ADMIN_LOCK)
            if await session.scalar(select(exists().where(User.role == "admin", User.is_active))):
                raise APIError(
                    409, "admin_exists", "An active administrator already exists; use the user API"
                )
            user = User(**data.model_dump(exclude={"password"}), password_hash=encoded)
            session.add(user)
            await session.flush()
            session.add(
                AdminLog(
                    user_id=user.id, action="user.bootstrap", entity_type="user", entity_id=user.id
                )
            )
    finally:
        await engine.dispose()


def main() -> None:
    name = input("Administrator name: ").strip()
    email = input("Administrator email: ").strip()
    password = getpass.getpass("Password (12–128 characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        data = UserCreate(name=name, email=email, password=password, role="admin")
        asyncio.run(bootstrap(data))
    except ValidationError:
        raise SystemExit("Invalid name, email or password; no account created") from None
    except Exception:
        raise SystemExit(
            "Bootstrap failed; verify connectivity, migrations and absence of an existing admin"
        ) from None
    print("Administrator created")


if __name__ == "__main__":
    main()
