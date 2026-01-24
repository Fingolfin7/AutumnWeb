from abc import ABC, abstractmethod


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
    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data the LLM is working with"""
        pass
