from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

ExecutionPhase = Literal[
    "understanding",
    "searching",
    "reading",
    "validating",
    "writing",
]

_listeners: ContextVar[tuple[Callable[[ExecutionPhase], None], ...]] = ContextVar(
    "execution_phase_listeners",
    default=(),
)


@contextmanager
def observe_phases(listener: Callable[[ExecutionPhase], None]) -> Iterator[None]:
    token = _listeners.set((*_listeners.get(), listener))
    try:
        yield
    finally:
        _listeners.reset(token)


def report_phase(phase: ExecutionPhase) -> None:
    for listener in _listeners.get():
        listener(phase)
