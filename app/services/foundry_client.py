from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient


class FoundryClient:
    """
    Wrap Azure AI Projects Agent reference call into a simple function.
    """

    def __init__(self, endpoint: str, agent_name: str):
        self.endpoint = endpoint
        self.agent_name = agent_name

        # DefaultAzureCredential:
        # - Local dev: az login / VS Code Azure sign-in
        # - Azure: Managed Identity / Workload Identity
        self.credential = DefaultAzureCredential()

        self.project_client = AIProjectClient(
            endpoint=self.endpoint,
            credential=self.credential,
        )

        self.openai_client = self.project_client.get_openai_client()

        # resolve agent once at startup (fail fast if name wrong)
        self.agent = self.project_client.agents.get(agent_name=self.agent_name)

    def chat_once(self, user_message: str) -> str:
        """
        Send one user message to the Foundry agent and return output text.
        """
        response = self.openai_client.responses.create(
            input=[{"role": "user", "content": user_message}],
            extra_body={"agent": {"name": self.agent.name, "type": "agent_reference"}},
        )
        return response.output_text
