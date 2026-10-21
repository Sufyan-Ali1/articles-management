from typing import TypeVar

from app.schemas.common import Meta, Page, Pagination

T = TypeVar("T")


def page_response(data: list[T], total: int, params: Pagination) -> Page[T]:
    return Page(
        data=data,
        meta=Meta(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=(total + params.page_size - 1) // params.page_size,
        ),
    )
