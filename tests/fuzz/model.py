"""Independent role and configuration state for one machine example."""
from dataclasses import dataclass, field


@dataclass
class Model:
    deployer: str
    borrowers: tuple[str, ...]
    holders: tuple[str, ...]
    liquidators: tuple[str, ...]
    merchants: tuple[str, ...]
    owner: str
    pending_owner: str | None = None
    approved_merchants: set[str] = field(default_factory=set)
