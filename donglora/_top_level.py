"""Module-level convenience singletons so ``import donglora as dl`` gives
one-line TX / RX scripts a Dongle without any explicit setup.

.. code-block:: python

    import donglora as dl

    dl.tx(b"hello")                 # lazy auto-connect on first call
    for pkt in dl.rx():             # same — lazy auto-connect
        print(pkt.rssi_dbm, pkt.data)

Users who need multiple connections, explicit configs, or context-manager
lifetimes should call :func:`donglora.connect` directly and use the
returned :class:`Dongle`.
"""

from __future__ import annotations

import atexit
import contextlib
import threading
from collections.abc import Iterator

from donglora.dongle import Dongle
from donglora.events import RxEvent, TxDone

_default: Dongle | None = None
_lock = threading.Lock()


def _get_default() -> Dongle:
    """Return (lazily creating) the process-wide default :class:`Dongle`."""
    global _default
    with _lock:
        if _default is None:
            from donglora.connect import connect

            _default = connect()
            atexit.register(_cleanup)
        return _default


def _cleanup() -> None:
    global _default
    with _lock:
        d = _default
        _default = None
    if d is not None:
        with contextlib.suppress(Exception):
            d.close()


def tx(data: bytes, *, skip_cad: bool = False, timeout: float = 10.0) -> TxDone:
    """One-line transmit. Creates the default dongle on first call."""
    return _get_default().tx(data, skip_cad=skip_cad, timeout=timeout)


def rx(timeout: float | None = None) -> Iterator[RxEvent]:
    """One-line continuous receive. Lazy-connects on first call."""
    return iter(_get_default().rx(timeout))


def recv(timeout: float | None = None) -> RxEvent | None:
    """One packet. Lazy-connects on first call."""
    return _get_default().recv(timeout)


def close() -> None:
    """Close the default dongle, if any. Safe to call multiple times."""
    _cleanup()
