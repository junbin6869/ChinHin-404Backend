import httpx


class FoundryClient:
    def __init__(self, endpoint: str, api_key: str, deployment: str):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment

    async def chat_once(self, user_message: str) -> str:
        url = (
            f"{self.endpoint}/openai/deployments/"
            f"{self.deployment}/chat/completions?api-version=2024-05-01-preview"
        )

        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }

        body = {
            "messages": [
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=body)

        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]
