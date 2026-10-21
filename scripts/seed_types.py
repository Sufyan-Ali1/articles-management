import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_database
from app.models import ArticleType

TYPES = (
    "tutorial",
    "product-review",
    "comparison",
    "buying-guide",
    "troubleshooting",
    "repair-guide",
    "informational",
)


async def seed(session: AsyncSession) -> None:
    for slug in TYPES:
        await session.execute(
            insert(ArticleType)
            .values(name=slug.replace("-", " ").title(), slug=slug)
            .on_conflict_do_nothing(index_elements=[ArticleType.slug])
        )


async def main() -> None:
    engine, factory = create_database(get_settings())
    try:
        async with factory() as session, session.begin():
            await seed(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
