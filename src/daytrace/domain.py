"""Platform-independent observations. No keyboard or content APIs."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    state: str = "active"
    process_name: str | None = None
    app_id: str | None = None
    title: str | None = None
    window: int = 0  # Transient only; never used as a durable application identity.

    def anonymous(self, state: str):
        return Observation(state)


STATES = {"active", "idle", "paused", "locked", "suspended", "excluded", "unknown"}
