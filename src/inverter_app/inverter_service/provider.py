import threading
from collections.abc import Iterator
from contextlib import contextmanager

from pysolarmanv5 import NoSocketAvailableError, V5FrameError

from src.inverter_app.inverter_service.manager import (
    InverterManager,
    InverterStats,
)

_lock = threading.Lock()


@contextmanager
def get_inverter_manager() -> Iterator[InverterManager]:
    """
    Connected InverterManager for the duration of the `with` block.
    Access is serialized: the logger handles few concurrent clients.
    """
    with _lock, InverterManager() as manager:
        yield manager


def read_latest_energy() -> InverterStats:
    try:
        with get_inverter_manager() as inverter:
            stats = inverter.read_registers()
        return stats
    except (OSError, V5FrameError, NoSocketAvailableError) as e:
        raise ConnectionError("Failed to connect to inverter") from e
