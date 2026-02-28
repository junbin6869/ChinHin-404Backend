from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
import threading

AgentKey = Literal["routing", "promotion", "procurement", "document", "general"]


@dataclass
class PendingState:
    agent: AgentKey
    original_request: str
    clarify_question: str


class Orchestrator:
    def __init__(self, foundry):
        self.foundry = foundry
        self._lock = threading.Lock()
        self._pending: dict[str, PendingState] = {}

    def _is_clarify(self, text: str) -> bool:
        return text.strip().lower().startswith("clarify:")

    def _strip_clarify(self, text: str) -> str:
        # Return only the part after "CLARIFY:"
        t = text.strip()
        idx = t.lower().find("clarify:")
        if idx == -1:
            return t
        return t[idx + len("clarify:"):].strip()

    def _normalize_route_output(self, raw: str) -> Optional[AgentKey]:
        if not raw:
            return None
        x = raw.strip().lower().replace('"', "").replace("'", "").strip()
        x = x.split()[0] if x else ""
        if x in ("promotion", "procurement", "document","geneeral"):
            return x  # type: ignore[return-value]
        return None

    def route(self, user_message: str) -> AgentKey:
        """
        No local prompt. Use cloud routing agent prompt.
        Expect routing agent to return: promotion|procurement|document
        """
        raw = self.foundry.chat_once("routing", user_message)
        agent = self._normalize_route_output(raw)
        if agent:
            return agent

        # Fallback: if routing output unexpected
        return "general"

    #step 3: check whether is new / pending msg
    def handle(self, conversation_id: str, user_message: str) -> str:
        """
        Main entry:
        - If pending: send user answer back to the pending agent with context
        - Else: route -> call chosen agent
        - If agent responds with CLARIFY: ... -> store pending and return only question part
        - Else: clear pending and return final answer
        """

        # 1) If pending, continue with same agent
        with self._lock:
            pending = self._pending.get(conversation_id)

        if pending:
            # Provide minimal context so agent can continue correctly (because calls are stateless)
            stitched = (
                f"Original user request:\n{pending.original_request}\n\n"
                f"You asked the user:\n{pending.clarify_question}\n\n"
                f"User answer:\n{user_message}\n\n"
                "Continue and provide the final answer."
            )
            out = self.foundry.chat_once(pending.agent, stitched)

            if self._is_clarify(out):
                # Still missing info: update clarify question (keep pending)
                q = self._strip_clarify(out)
                with self._lock:
                    self._pending[conversation_id] = PendingState(
                        agent=pending.agent,
                        original_request=pending.original_request,
                        clarify_question=q,
                    )
                return q

            # Completed: clear pending
            with self._lock:
                self._pending.pop(conversation_id, None)
            return out

        # 2) Not pending: route and call agent
        agent = self.route(user_message)
        out = self.foundry.chat_once(agent, user_message)

        # 3) If clarify, store pending and return question only
        if self._is_clarify(out):
            q = self._strip_clarify(out)
            with self._lock:
                self._pending[conversation_id] = PendingState(
                    agent=agent,
                    original_request=user_message,
                    clarify_question=q,
                )
            return q

        return out