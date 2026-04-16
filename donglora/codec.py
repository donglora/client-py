"""Backwards-compatible COBS codec helpers.

The v1.0 wire layer lives in :mod:`donglora.frame`. This module keeps
the thin helpers that the old client exposed (``cobs_encode``,
``read_frame``) so unrelated transport glue keeps working.
"""

from __future__ import annotations

from cobs import cobs

from donglora.frame import Frame, Readable, read_frame  # noqa: F401 — re-export


def cobs_encode(data: bytes) -> bytes:
    """COBS-encode *data* and append the ``0x00`` sentinel.

    Exposed for transport-level pass-through; regular callers should go
    through :func:`donglora.frame.encode_frame` instead.
    """
    return cobs.encode(data) + b"\x00"
