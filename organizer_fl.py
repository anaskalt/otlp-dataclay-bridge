"""Distributed queues for FL run orchestration.
goal is: it is automatically imported by the dataClay stub‑loader

"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dataclay import DataClayObject, activemethod

# ──────────────────────────────────────────────────────────────────────────────
# Parameter object travelling through the queue
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Parameters(DataClayObject):
    """Configuration sent from the Intelligence Coordinator to the FL runner."""

    # Whether to stream weights (True) or checkpoint at the end.
    use_stream: bool = False
    # Arbitrary run‑time configuration forwarded to `flwr run`.
    run_config: dict[str, str] | None = None
    # "start" | "stop" | future actions ("health", ...)
    action: str = "start"

# ──────────────────────────────────────────────────────────────────────────────
# Persistent coordination object
# ──────────────────────────────────────────────────────────────────────────────
class OrganizerFL(DataClayObject):
    """Two in‑memory queues persisted by dataClay (triggers ↔ results)."""

    trigger_queue: list[Parameters]
    results: list[dict | str]

    # NOTE: initialization is called on object creation, before dataClay persistence
    def __init__(self):
        super().__init__()
        self.trigger_queue = []
        self.results = []

    #  Producer side  ──────────────────────────────────────────────────────────
    @activemethod
    def new_trigger(self, parameters: Parameters) -> None:
        """Enqueue a new FL action."""
        self.trigger_queue.append(parameters)

    #  Consumer side  ──────────────────────────────────────────────────────────
    @activemethod
    def get_trigger(self) -> Optional[Parameters]:
        """Blocking pop with timeout (returns *None* on timeout)."""
        try:
            return self.trigger_queue.pop()
        except IndexError:
            return None

    #  Runner → Controller  ────────────────────────────────────────────────────
    @activemethod
    def send_results(self, results: dict | str) -> None:
        self.results.append(results)

    @activemethod
    def get_results(self) -> Optional[dict | str]:
        try:
            return self.results.pop()
        except IndexError:
            return None
