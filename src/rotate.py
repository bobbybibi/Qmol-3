"""API key rotation: burn a compromised key and issue a new one for the same email+tier.

Rotation preserves team membership (new key is added to the same team, old one removed)
and preserves month-to-date usage history (audit rows keep old key).
"""
from __future__ import annotations
from dataclasses import dataclass

from src import keys as keysdb
from src import teams as _teams


@dataclass
class RotateResult:
    old_key: str
    new_key: str
    email: str
    tier: str


def rotate(old_key: str) -> RotateResult:
    info = keysdb.lookup(old_key)
    if not info:
        raise ValueError("Unknown API key")

    # Revoke old first so a double-rotate can't re-hand it out.
    keysdb.deactivate(old_key)

    # Provision fresh; lookup forces a new token because old is inactive.
    new_info = keysdb.provision(info.email, info.tier)

    # Preserve team membership.
    team = _teams.team_for_key(old_key)
    if team:
        _teams.remove_member(team.id, old_key)
        _teams.add_member(team.id, new_info.key)

    return RotateResult(old_key=old_key, new_key=new_info.key,
                        email=info.email, tier=info.tier)
