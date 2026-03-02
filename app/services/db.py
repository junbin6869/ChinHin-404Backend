# app/services/db.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# Regex pattern to block dangerous SQL keywords
DANGEROUS_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|merge|exec|execute|grant|revoke|create)\b",
    re.IGNORECASE,
)


@dataclass
class DBConfig:
    db_url: str
    allowed_objects: Optional[Sequence[str]] = None
    default_row_limit: int = 500


class Database:
    """
    Database wrapper responsible for:
    - Managing DB connection
    - Validating SQL safety
    - Executing parameterized SELECT queries
    """

    def __init__(self, cfg: DBConfig):
        self.cfg = cfg
        self._engine: Optional[Engine] = None

    def init(self) -> None:
        """Initialize SQLAlchemy engine."""
        if self._engine is None:
            self._engine = create_engine(self.cfg.db_url, pool_pre_ping=True)

    def close(self) -> None:
        """Dispose engine on shutdown."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    @property
    def engine(self) -> Engine:
        if not self._engine:
            raise RuntimeError("Database not initialized.")
        return self._engine

    # -------------------------
    # SQL Safety Validation
    # -------------------------

    def validate_select_only(self, sql: str) -> None:
        """
        Enforce:
        - Only SELECT statements
        - No multiple statements
        - No dangerous keywords
        - Optional whitelist of tables/views
        """

        s = sql.strip()

        # Disallow multiple statements
        if ";" in s:
            raise ValueError("Multiple SQL statements are not allowed.")

        # Must start with SELECT or WITH (CTE)
        if not re.match(r"^(with\s+[\s\S]+?\)\s*select|select)\b", s, re.IGNORECASE):
            raise ValueError("Only SELECT queries are allowed.")

        # Block dangerous keywords
        if DANGEROUS_SQL.search(s):
            raise ValueError("Dangerous SQL keyword detected.")

        # Optional object whitelist check
        if self.cfg.allowed_objects:
            tokens = re.findall(r"\b(from|join)\s+([a-zA-Z0-9_\.\[\]]+)", s, re.IGNORECASE)
            objects = [t[1].strip("[]").lower() for t in tokens]
            allowed = {o.lower() for o in self.cfg.allowed_objects}

            for obj in objects:
                base = obj.split(".")[-1]
                if obj not in allowed and base not in allowed:
                    raise ValueError(f"Access to object '{obj}' is not allowed.")

    def _enforce_limit(self, sql: str, row_limit: int) -> str:
        """
        Add row limit protection (SQL Server style TOP).
        Skip if TOP or LIMIT already exists.
        """

        if re.search(r"\btop\s+\d+\b", sql, re.IGNORECASE) or re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
            return sql

        if re.match(r"^select\b", sql.strip(), re.IGNORECASE):
            return re.sub(r"^select\b", f"SELECT TOP {row_limit}", sql, flags=re.IGNORECASE)

        return sql

    # -------------------------
    # Query Execution
    # -------------------------

    def query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        row_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a validated SELECT query with parameter binding.
        """

        self.validate_select_only(sql)

        final_sql = self._enforce_limit(sql, row_limit or self.cfg.default_row_limit)

        with self.engine.connect() as conn:
            result = conn.execute(text(final_sql), params or {})
            rows = result.fetchall()
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in rows]