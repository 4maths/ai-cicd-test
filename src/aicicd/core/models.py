from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeployGuardResult:
    target_url: str
    status_code: int | None
    latency_ms: int | None
    health_status: str
    decision: str
    summary: str
    checks: list[str] = field(default_factory=list)