from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    @abstractmethod
    def initialize_chat(self, username, sessions_data):
        pass

    @abstractmethod
    async def send_message(self, message) -> str:
        pass

    @abstractmethod
    def get_conversation_history(self) -> list:
        pass

    @abstractmethod
    def set_conversation_history(self, history: list):
        """Set the conversation history from a list of dicts"""
        pass

    @abstractmethod
    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data the LLM is working with"""
        pass

    async def stream_message(self, message) -> AsyncIterator[str]:
        """Stream a message response.

        Handlers can override this for token-by-token SDK streaming. The default
        keeps older handlers compatible by yielding the final response as one
        chunk after send_message updates the conversation history.
        """
        response = await self.send_message(message)
        if response:
            yield response

    async def stream_update_session_data(
        self, sessions_data, user_prompt
    ) -> AsyncIterator[str]:
        """Stream a response after updating the session data context."""
        response = await self.update_session_data(sessions_data, user_prompt)
        if response:
            yield response

    async def generate_chat_title(self, prompt: str) -> str:
        """Generate a short title without mutating the conversation history."""
        return ""
