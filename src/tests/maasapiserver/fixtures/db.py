from os.path import abspath
import random
import string
from typing import Any, AsyncGenerator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.operators import ColumnOperators

from maasapiserver.db import Database
from maasapiserver.db.tables import METADATA
from maasapiserver.settings import DatabaseConfig
from maastesting.pytest.database import cluster_stash


@pytest.fixture
def db(
    request: pytest.FixtureRequest, ensuremaasdb: str
) -> Iterator[Database]:
    """Set up the database schema."""
    echo = request.config.getoption("sqlalchemy_debug")
    db_config = DatabaseConfig(ensuremaasdb, host=abspath("db/"))
    yield Database(db_config, echo=echo)


@pytest.fixture
async def db_connection(
    request: pytest.FixtureRequest, pytestconfig, db: Database
) -> AsyncGenerator[AsyncConnection, None]:
    """A database session."""
    allow_transactions = (
        request.node.get_closest_marker("allow_transactions") is not None
    )
    conn = await db.engine.connect()
    if allow_transactions:
        try:
            yield conn
        finally:
            await conn.close()
            cluster = pytestconfig.stash[cluster_stash]
            cluster.dropdb(db.config.name)
    else:
        await conn.begin()
        try:
            yield conn
        finally:
            await conn.rollback()
            await conn.close()


class Fixture:
    """Helper for creating test fixtures."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def commit(self) -> None:
        await self.conn.commit()

    async def create(
        self,
        table: str,
        data: dict[str, Any] | list[dict[str, Any]] | None = None,
        commit: bool = False,
    ) -> list[dict[str, Any]]:
        result = await self.conn.execute(
            METADATA.tables[table].insert().returning("*"), data
        )
        if commit:
            await self.conn.commit()
        return [row._asdict() for row in result]

    async def get(
        self,
        table: str,
        *filters: ColumnOperators,
    ) -> list[dict[str, Any]]:
        """Take a peak what is in there"""
        table_cls = METADATA.tables[table]
        result = await self.conn.execute(
            table_cls.select()
            .where(*filters)  # type: ignore[arg-type]
            .order_by(table_cls.c.id)
        )
        return [row._asdict() for row in result]

    def random_string(self, length: int = 10) -> str:
        return "".join(random.choices(string.ascii_letters, k=length))


@pytest.fixture
def fixture(db_connection: AsyncConnection) -> Iterator[Fixture]:
    yield Fixture(db_connection)