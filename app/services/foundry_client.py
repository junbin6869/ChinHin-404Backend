from __future__ import annotations

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient


class FoundryClient:
    """
    Multi-agent wrapper:
      agent_map: { "routing": "...", "promotion": "...", "procurement": "...", "document": "..." }
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

    def chat_once(self, agent_key: str, user_message: str) -> str:
        if agent_key not in self._agents:
            raise ValueError(f"Unknown agent_key='{agent_key}'. Available: {list(self._agents.keys())}")

        agent_obj = self._agents[agent_key]

        response = self.openai_client.responses.create(
            input=[{"role": "user", "content": user_message}],
            extra_body={
                "agent_reference": {
                    "type": "agent_reference",
                    "name": agent_obj.name,
                },
        })
        return response.output_text