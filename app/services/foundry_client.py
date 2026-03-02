from __future__ import annotations

from typing import Any, Optional

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient


class FoundryClient:
    """
    Multi-agent wrapper:
      agent_map: { "routing": "...", "promotion": "...", "procurement": "...", "document": "...", "general": "...", "data_fetch": "..." }
    """

    def __init__(self, endpoint: str, agent_map: dict[str, str]):
        self.endpoint = endpoint
        self.agent_map = agent_map

        self.credential = DefaultAzureCredential()
        self.project_client = AIProjectClient(
            endpoint=self.endpoint,
            credential=self.credential,
        )
        self.openai_client = self.project_client.get_openai_client()

        # Resolve all agents once at startup
        self._agents: dict[str, object] = {}
        for key, agent_name in self.agent_map.items():
            self._agents[key] = self.project_client.agents.get(agent_name=agent_name)

    def _to_responses_input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            # 只处理最常见的 string content；如果不是 string，就转成 string
            if isinstance(content, list):
                # 例如你未来可能传 [{"type":"input_text","text":"..."}]，那就拼起来
                content = " ".join(
                    (c.get("text") if isinstance(c, dict) else str(c)) for c in content
                )
            if content is None:
                content = ""
            content = str(content)

            # 避免空消息（空消息会导致 invalid_value）
            if not content.strip():
                continue

            input_items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": [{"type": "input_text", "text": content}],
                }
            )

        return input_items

    def call_agent(
        self,
        agent_key: str,
        messages: list[dict[str, Any]],
        conversation_id: Optional[str] = None,
    ) -> str:
        if agent_key not in self._agents:
            raise ValueError(f"Unknown agent_key='{agent_key}'. Available: {list(self._agents.keys())}")

        agent_obj = self._agents[agent_key]

        input_items = self._to_responses_input(messages)
        if not input_items:
            raise ValueError("No valid input messages to send (all empty).")

        response = self.openai_client.responses.create(
            input=input_items,
            extra_body={
                "agent_reference": {
                    "type": "agent_reference",
                    "name": agent_obj.name,
                },
            },
        )
        return response.output_text

    def chat_once(self, agent_key: str, user_message: str) -> str:
        return self.call_agent(
            agent_key=agent_key,
            messages=[{"role": "user", "content": user_message}],
            conversation_id=None,
        )