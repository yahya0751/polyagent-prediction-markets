"""Compliance gate.

Hard rule: in MODE=PAPER_TRADING, anything goes. In any other mode,
this module's `block_reasons()` must return [] before any order is placed.

Polymarket prohibits US persons under its ToS. We don't trust IP
geolocation alone — we require the operator to assert their
jurisdiction explicitly via env var, and we require it to be on the
allowlist in config.yaml.
"""
from __future__ import annotations

from ..config import Settings
from ..types import Mode

# Jurisdictions Polymarket explicitly bars in its ToS (operator must
# never override this set). This is defense in depth on top of platform
# geofencing — the platform may also enforce it independently.
HARD_BLOCKED_JURISDICTIONS = {
    "US",  # United States
    # Add others as platform ToS require.
}


def block_reasons(settings: Settings, target_platform: str = "polymarket") -> list[str]:
    out: list[str] = []
    sec = settings.secrets

    # Paper mode is always allowed.
    if sec.mode is Mode.PAPER:
        return out

    # Platform allowlist
    if target_platform not in settings.compliance.allowed_platforms:
        out.append(f"platform '{target_platform}' not in allowed_platforms")

    # Jurisdiction must be set
    j = sec.compliance_jurisdiction.upper()
    if not j:
        out.append("COMPLIANCE_JURISDICTION not set")
    else:
        if j in HARD_BLOCKED_JURISDICTIONS:
            out.append(f"jurisdiction {j} is on the platform's hard-block list")
        if j not in [c.upper() for c in settings.compliance.allowed_jurisdictions]:
            out.append(f"jurisdiction {j} not in compliance.allowed_jurisdictions")

    # ToS acknowledgement
    if sec.compliance_tos_ack != "I_HAVE_READ_TOS":
        out.append("COMPLIANCE_TOS_ACK not set to I_HAVE_READ_TOS")

    # AUTO_TRADING gating: config can force MANUAL approval.
    if sec.mode is Mode.AUTO and settings.compliance.require_manual_approval:
        out.append("compliance.require_manual_approval=true blocks AUTO_TRADING")

    return out


def assert_can_trade(settings: Settings, target_platform: str = "polymarket") -> None:
    reasons = block_reasons(settings, target_platform)
    if reasons:
        raise PermissionError(
            "Trading blocked by compliance gate:\n  - " + "\n  - ".join(reasons)
        )
