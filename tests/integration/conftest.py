"""Fixtures for integration tests (require a real Postgres).

Each test gets a fresh async engine bound to its own event loop and a clean
schema, so tests are isolated and order-independent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

import app.infrastructure.db.session as db_session
from app.infrastructure.db.models import Base


@pytest.fixture(autouse=True)
async def fresh_db():
    # Rebind the global engine to the current test's event loop.
    db_session._engine = None
    engine = db_session.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE prompt_items, jobs CASCADE"))
    yield
    await engine.dispose()
    db_session._engine = None
