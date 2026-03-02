# app/services/orchestrator.py
from __future__ import annotations
from decimal import Decimal
from datetime import date, datetime

import json
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from app.services.db import Database


AgentKey = Literal["routing", "data_fetch", "promotion", "procurement", "document", "general"]


@dataclass
class OrchestratorResult:
    agent: AgentKey
    reply: str
    debug: Optional[Dict[str, Any]] = None


class Orchestrator:
    """
    Orchestration flow:

    routing -> data_fetch -> database -> business_agent
    """

    def __init__(self, foundry_client: Any, db: Database):
        self.foundry = foundry_client
        self.db = db
        #service which need data
        self.data_required_intents = {"promotion", "procurement"}

    def _json_default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)

    def _parse_intent(self, raw: str) -> AgentKey:
        x = (raw or "").strip().lower()
        if x in self.data_required_intents or x in {"document", "general"}:
            return x  # type: ignore
        return "general"

    def _safe_json_loads(self, raw: str) -> Dict[str, Any]:
        """
        Safely parse JSON from data_fetch agent.
        Strips markdown fences if present.
        """
        t = raw.strip()

        if t.startswith("```"):
            t = t[t.find("{") : t.rfind("}") + 1]

        return json.loads(t)

    def handle(self, user_message: str, conversation_id: Optional[str] = None) -> OrchestratorResult:

        # Step 1: Call routing agent
        routing_raw = self.foundry.call_agent(
            agent_key="routing",
            messages=[{"role": "user", "content": user_message}],
            conversation_id=conversation_id,
        )

        intent = self._parse_intent(routing_raw)

        debug: Dict[str, Any] = {"routing_raw": routing_raw, "intent": intent}

        rows = None
        fetch_reason = None

        # Step 2: If intent requires data, call data_fetch agent
        if intent in self.data_required_intents:

            fetch_raw = self.foundry.call_agent(
                agent_key="data_fetch",
                messages=[
                    {"role": "user", "content": user_message},
                    {"role": "system", "content": f"INTENT: {intent}"}
                ],
                conversation_id=conversation_id,
            )

            debug["fetch_raw"] = fetch_raw

            fetch_json = self._safe_json_loads(fetch_raw)

            sql = fetch_json.get("sql")
            params = fetch_json.get("params", {})
            fetch_reason = fetch_json.get("reason")

            debug["fetch_sql"] = sql
            debug["fetch_params"] = params
            debug["fetch_reason"] = fetch_reason

            # Execute SQL via db layer
            rows = self.db.query(sql, params=params)

            debug["rows_count"] = len(rows)

        # Step 3: Send processed context to business agent
        context_payload = {}

        if rows is not None:
            context_payload = {
                "rows_preview": rows[:50],
                "rows_count": len(rows),
                "fetch_reason": fetch_reason,
                "note": "Only first 50 rows provided."
            }

        business_messages = [
            {"role": "user", "content": user_message},
            {"role": "system", "content": json.dumps(context_payload, default=self._json_default)}
        ]

        business_raw = self.foundry.call_agent(
            agent_key=intent,
            messages=business_messages,
            conversation_id=conversation_id,
        )

        return OrchestratorResult(agent=intent, reply=business_raw, debug=debug)