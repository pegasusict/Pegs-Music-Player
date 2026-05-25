from datetime import datetime, timezone

from infrastructure.database import Database
from infrastructure.queries import spread_queries as queries


class SpreadStateRepository:
    """Repository for managing the spread state of categories."""
    def __init__(self, database: Database):
        self._db = database

    def save(
        self,
        category: str,
        period_id: str,
        target: int,
        played: int,
        accumulator: float,
    ) -> None:
        """Saves the spread state for a given category."""
        with self._db.connect() as con:
            con.execute(
                queries.INSERT_OR_REPLACE,
                (
                    category,
                    period_id,
                    target,
                    played,
                    accumulator,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def load(self, category: str) -> dict[str, int | float] | None:
        """Loads the spread state for a given category."""
        with self._db.connect() as con:
            row = con.execute(
                queries.SELECT_BY_CATEGORY,
                (category,),
            ).fetchone()

        if not row:
            return None

        return {
            "period_id": row[0],
            "target": row[1],
            "played": row[2],
            "accumulator": row[3],
        }

    def clear(self, category: str) -> None:
        """Clears the spread state for a given category."""
        with self._db.connect() as con:
            con.execute(
                queries.DELETE_BY_CATEGORY,
                (category,),
            )
