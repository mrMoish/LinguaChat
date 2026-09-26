import httpx
from backend.core.config import OPENROUTER_TIMEOUT

class AsyncClientManager:
    def __init__(self):
        self.client = None

    async def get_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT)
        return self.client

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

# Shared global instance
client_manager = AsyncClientManager()
