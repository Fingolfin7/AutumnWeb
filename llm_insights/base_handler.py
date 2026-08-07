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

    def set_conversation_history(self, history: list):
        """Adopt the stored history for this request.

        Copied, never aliased. The caller keeps its own reference as the
        pre-turn boundary for failure recovery, and handlers append in place —
        sharing one list makes that boundary move along with the handler, so
        the recovery delta computes to nothing and the turn's real entries are
        replaced by a synthetic error pair.
        """
        self.conversation_history = list(history)

    @abstractmethod
    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data the LLM is working with"""
        pass

    def has_system_context(self) -> bool:
        """Whether this handler can produce instructions plus session data.

        False for a resumed chat whose stored history carries no system turn —
        a chat from before system turns were stored, or one whose first turn
        failed before storing it. Without re-seeding, the model would answer
        with no instructions and no session data at all.
        """
        active = getattr(self, "_active_system_text", None)
        return bool(active()) if callable(active) else True

    def set_username(self, username):
        """Re-seed the display name on a resumed chat.

        initialize_chat only runs for new chats, so a handler built to answer
        turn 2+ starts with username unset — and the prompt templates
        interpolate it.
        """
        if username and not getattr(self, "username", None):
            self.username = username

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
