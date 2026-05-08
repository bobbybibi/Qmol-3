"""Admin CLI: revenue + usage reports from keys.sqlite.

Usage:
    python -m admin report
    python -m admin top-users --limit 20
    python -m admin revenue
    python -m admin revoke <api_key>
    python -m admin issue <email> <tier>
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

import typer

from src import keys as keysdb

# Rough monthly-equivalent prices for recurring-revenue view (one-time sales).
TIER_PRICE = {
    "free": 0,
    "research": 29,
    "commercial": 299,
    "redistribution": 999,
    "enterprise": 5000,
}

app = typer.Typer(help="Q-Mol admin console")


def _conn() -> sqlite3.Connection:
    return keysdb._connect()


@app.command()
def report():
    """Summary: active keys per tier, total calls, SMILES processed this month."""
    c = _conn()
    typer.echo("=== Active keys by tier ===")
    for row in c.execute(
        "SELECT tier, COUNT(*) FROM api_keys WHERE active=1 GROUP BY tier"
    ):
        typer.echo(f"  {row[0]:<16} {row[1]}")

    total_calls = c.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
    total_smi = c.execute("SELECT COALESCE(SUM(smiles_count),0) FROM usage").fetchone()[0]
    month_smi = c.execute(
        "SELECT COALESCE(SUM(smiles_count),0) FROM usage "
        "WHERE ts >= datetime('now','start of month')"
    ).fetchone()[0]
    typer.echo(f"\nTotal API calls ever: {total_calls:,}")
    typer.echo(f"Total SMILES processed: {total_smi:,}")
    typer.echo(f"SMILES this month: {month_smi:,}")
    c.close()


@app.command()
def revenue():
    """Approximate lifetime revenue from active paid keys."""
    c = _conn()
    total = 0
    typer.echo("=== Revenue by tier (one-time sales) ===")
    for row in c.execute(
        "SELECT tier, COUNT(*) FROM api_keys WHERE active=1 GROUP BY tier"
    ):
        tier, count = row
        price = TIER_PRICE.get(tier, 0)
        subtotal = price * count
        total += subtotal
        if price:
            typer.echo(f"  {tier:<16} {count:>4} x ${price:<5} = ${subtotal:,}")
    typer.echo(f"\nLifetime revenue (est): ${total:,}")
    c.close()


@app.command("top-users")
def top_users(limit: int = typer.Option(10, "--limit", "-n")):
    """Heaviest users this month."""
    c = _conn()
    q = """
    SELECT u.key, k.email, k.tier, SUM(u.smiles_count) AS n
    FROM usage u
    JOIN api_keys k ON k.key = u.key
    WHERE u.ts >= datetime('now','start of month')
    GROUP BY u.key
    ORDER BY n DESC
    LIMIT ?
    """
    typer.echo(f"{'email':<32} {'tier':<14} {'smiles':>10}")
    for row in c.execute(q, (limit,)):
        typer.echo(f"{row[1]:<32} {row[2]:<14} {int(row[3]):>10,}")
    c.close()


@app.command()
def issue(email: str, tier: str = "research"):
    """Manually issue an API key (for giveaways, support cases)."""
    info = keysdb.provision(email, tier)
    typer.echo(f"Issued: {info.key}  tier={info.tier}  quota={info.monthly_quota:,}")


@app.command()
def revoke(api_key: str):
    """Deactivate a key."""
    keysdb.deactivate(api_key)
    typer.echo(f"Revoked: {api_key}")


def main():
    app()


if __name__ == "__main__":
    main()
