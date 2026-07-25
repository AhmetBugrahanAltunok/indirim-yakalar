"""Başlangıç — boş temel revizyon

Faz 0 iskeletinin migration zincirini başlatır. Tablolar Faz 1'de eklenir
(markets, depots, raw_records, products, price_history, watchlist, settings).

Revision ID: 0001
Revises:
Create Date: 2026-07-25
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
