from abc import ABC, abstractmethod
from typing import AsyncIterator

from .session_context import SESSION_DATA_SLOT, encode_session_data, render_session_prompt


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    def initialize_chat(self, username, sessions_data, *, force_refresh=False):
        self.username = username
        self.session_data = encode_session_data(
            sessions_data, username=username, force_refresh=force_refresh
        )

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
        return any(
            message.get("role") == "system" and message.get("content")
            for message in self.conversation_history
        )

    def _build_system_text(self, notice: str = "") -> str:
        body = self.system_prompt_template.format(
            username=self.username, session_data=SESSION_DATA_SLOT
        )
        return f"{notice.strip()}\n{body}" if notice.strip() else body

    def _active_system_text(self) -> str:
        """Use the most recent stored instructions with this request's sessions."""
        for message in reversed(self.conversation_history):
            if message.get("role") == "system" and message.get("content"):
                stored = message["content"]
                rendered = render_session_prompt(stored, self.session_data)
                if self.session_data is None or rendered != stored:
                    return rendered
                # Keep unrecognised text in history. Build a fresh prompt
                # instead of sending a possible frozen session copy.
                break
        if self.username and self.session_data is not None:
            return render_session_prompt(self._build_system_text(), self.session_data)
        return ""

    def set_username(self, username):
        """Set the display name before a filter update builds new instructions."""
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
