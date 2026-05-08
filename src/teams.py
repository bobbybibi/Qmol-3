"""Team accounts: share a single monthly quota across multiple API keys.

Enterprise buyers want one invoice + one pool of credits + many keys
(one per analyst, one per CI bot, etc). That's what this gives them.

Data model
----------
teams(id TEXT PK, name, tier, monthly_quota, owner_email, created_at)
team_members(team_id, api_key)    -- api_key references keys table

A key is in at most one team; when it is, the team's pooled usage gates
quota checks instead of the individual key's quota.
"""
from __future__ import annotations
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import List

from src import keys as keysdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    monthly_quota INTEGER NOT NULL,
    owner_email TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS team_members (
    team_id TEXT NOT NULL,
    api_key TEXT NOT NULL UNIQUE,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, api_key)
);
"""


@dataclass
class Team:
    id: str
    name: str
    tier: str
    monthly_quota: int
    owner_email: str | None
    member_count: int

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "tier": self.tier,
            "monthly_quota": self.monthly_quota,
            "owner_email": self.owner_email,
            "member_count": self.member_count,
        }


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def create(name: str, tier: str, monthly_quota: int,
           owner_email: str | None = None) -> Team:
    tid = "team_" + secrets.token_urlsafe(8)
    c = _conn()
    c.execute(
        "INSERT INTO teams (id, name, tier, monthly_quota, owner_email) "
        "VALUES (?,?,?,?,?)",
        (tid, name, tier, monthly_quota, owner_email),
    )
    c.commit()
    c.close()
    return Team(id=tid, name=name, tier=tier, monthly_quota=monthly_quota,
                owner_email=owner_email, member_count=0)


def add_member(team_id: str, api_key: str) -> None:
    c = _conn()
    c.execute("INSERT OR REPLACE INTO team_members (team_id, api_key) VALUES (?,?)",
              (team_id, api_key))
    c.commit()
    c.close()


def remove_member(team_id: str, api_key: str) -> None:
    c = _conn()
    c.execute("DELETE FROM team_members WHERE team_id=? AND api_key=?",
              (team_id, api_key))
    c.commit()
    c.close()


def team_for_key(api_key: str) -> Team | None:
    c = _conn()
    row = c.execute(
        "SELECT t.id, t.name, t.tier, t.monthly_quota, t.owner_email, "
        "(SELECT COUNT(*) FROM team_members WHERE team_id=t.id) "
        "FROM teams t JOIN team_members m ON m.team_id=t.id "
        "WHERE m.api_key=?",
        (api_key,),
    ).fetchone()
    c.close()
    if not row:
        return None
    return Team(*row)


def get(team_id: str) -> Team | None:
    c = _conn()
    row = c.execute(
        "SELECT id, name, tier, monthly_quota, owner_email, "
        "(SELECT COUNT(*) FROM team_members WHERE team_id=id) "
        "FROM teams WHERE id=?",
        (team_id,),
    ).fetchone()
    c.close()
    if not row:
        return None
    return Team(*row)


def members(team_id: str) -> list[str]:
    c = _conn()
    rows = c.execute(
        "SELECT api_key FROM team_members WHERE team_id=? ORDER BY added_at",
        (team_id,),
    ).fetchall()
    c.close()
    return [r[0] for r in rows]


def month_usage(team_id: str) -> int:
    """Total SMILES charged across all member keys this calendar month."""
    ks = members(team_id)
    if not ks:
        return 0
    return sum(keysdb.month_usage(k) for k in ks)


def effective_quota(api_key: str) -> tuple[int, int]:
    """Return (used_this_month, monthly_quota) using the team pool if member."""
    team = team_for_key(api_key)
    if team:
        return month_usage(team.id), team.monthly_quota
    info = keysdb.lookup(api_key)
    if not info:
        return 0, 0
    return keysdb.month_usage(api_key), info.monthly_quota
