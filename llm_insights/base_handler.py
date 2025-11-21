from abc import ABC, abstractmethod


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    @abstractmethod
    def initialize_chat(self, username, sessions_data):
        pass

    @abstractmethod
    def send_message(self, message):
        pass

    @abstractmethod
    def get_conversation_history(self):
        pass
    
    @abstractmethod
    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data the LLM is working with"""
        pass

