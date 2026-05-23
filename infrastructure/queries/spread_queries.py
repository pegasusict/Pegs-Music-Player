# infrastructure/queries/spread_queries.py

INSERT_OR_REPLACE = """
    INSERT OR REPLACE INTO spread_state
    (category, period_id, period_target, played_count, accumulator, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
"""

SELECT_BY_CATEGORY = """
    SELECT period_id, period_target, played_count, accumulator
    FROM spread_state
    WHERE category = ?
"""

DELETE_BY_CATEGORY = """
    DELETE FROM spread_state
    WHERE category = ?
"""