import threading
from collections.abc import Iterator
from contextlib import contextmanager

from src.inverter_app.inverter_service.manager import InverterManager

_lock = threading.Lock()


@contextmanager
def get_inverter_manager() -> Iterator[InverterManager]:
    """
    Connected InverterManager for the duration of the `with` block.
    Access is serialized: the logger handles few concurrent clients.
    """
    with _lock, InverterManager() as manager:
        yield manager
