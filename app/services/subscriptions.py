from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscriber
from app.schemas.subscriptions import SubscriptionCreate
from app.services.common import transaction


async def subscribe(session: AsyncSession, data: SubscriptionCreate) -> None:
    async with transaction(session):
        # The unique constraint handles simultaneous requests across API processes.
        # Duplicates receive the same response without changing the original timestamp.
        await session.execute(
            insert(Subscriber)
            .values(email=data.email)
            .on_conflict_do_nothing(index_elements=[Subscriber.email])
        )
