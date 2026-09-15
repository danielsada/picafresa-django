from contextvars import ContextVar, Token
from uuid import UUID, uuid4

_correlation_id: ContextVar[UUID | None] = ContextVar("correlation_id", default=None)


def begin_request_correlation() -> Token[UUID | None]:
    return _correlation_id.set(uuid4())


def end_request_correlation(token: Token[UUID | None]) -> None:
    _correlation_id.reset(token)


def current_correlation_id() -> UUID:
    return _correlation_id.get() or uuid4()
