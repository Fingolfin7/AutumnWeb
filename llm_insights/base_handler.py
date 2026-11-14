from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    @abstractmethod
    def initialize_chat(self, username, sessions_data):
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

    @staticmethod
    def _user_entry(message, attachments=None) -> dict:
        """A user turn for conversation history. Attachments ride along (see
        llm_insights.attachments.payload) so they are linked when saved and
        resent on later turns."""
        entry = {"role": "user", "content": message}
        if attachments:
            entry["attachments"] = list(attachments)
        return entry

    @abstractmethod
    def stream_message(self, message, attachments=None) -> AsyncIterator[str]:
        """Send a message and stream the response text, recording the turn in
        the conversation history."""

    @abstractmethod
    def stream_update_session_data(
        self, sessions_data, user_prompt, attachments=None
    ) -> AsyncIterator[str]:
        """Swap in new session data, then stream the response to user_prompt."""

    async def generate_chat_title(self, prompt: str) -> str:
        """Generate a short title without mutating the conversation history."""
        return ""
