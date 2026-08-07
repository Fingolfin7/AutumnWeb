from toon import encode
from anthropic import NOT_GIVEN, AsyncAnthropic
from typing import Any, AsyncIterator
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class ClaudeHandler(BaseLLMHandler):
    # The instructions and the session payload are the largest, most stable part
    # of every request and get resent on each turn, so they ride in `system` with
    # a cache breakpoint rather than inside the message list. Anything that
    # varies per turn (the user's prompt) must stay out of this block or the
    # cached prefix never matches.

    # max_tokens is required by the Messages API — there is no way to leave it
    # unset — so each model gets its documented output ceiling instead of an
    # arbitrary cap. Non-streaming calls can't use the ceiling: the SDK refuses
    # requests it estimates will outrun its HTTP timeout.
    MAX_OUTPUT_TOKENS = {
        "claude-fable-5": 128000,
        "claude-opus-5": 128000,
        "claude-sonnet-5": 128000,
        "claude-haiku-4-5": 64000,
    }
    DEFAULT_MAX_OUTPUT_TOKENS = 64000
    NON_STREAMING_MAX_OUTPUT_TOKENS = 16000

    def __init__(self, model="claude-sonnet-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key
        self.client = (
            AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
        )  # falls back to ANTHROPIC_API_KEY env
        self.username = None
        self.session_data = None
        self.conversation_history = []
        self.usage_stats = {"prompt": 0, "response": 0, "cached": 0, "total": 0}
        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.

        When formatting text and links please use markdown formatting.

        Sessions data:
        {session_data}
        """
        self.update_session_data_notice = """
        {username} has updated their session data.
        Refer to the new session data for the remainder of the conversation.
        """

    def initialize_chat(self, username, sessions_data):
        self.username = username
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )

    def _build_system_text(self, notice: str = "") -> str:
        body = self.system_prompt_template.format(
            username=self.username, session_data=self.session_data
        )
        return f"{notice.strip()}\n{body}" if notice.strip() else body

    def _active_system_text(self) -> str:
        """The system prompt for this request.

        The stored snapshot wins: every path that changes the session data also
        stores a fresh system turn, so the last one is always current — and
        reusing it verbatim keeps the cached prefix byte-identical across turns.
        Rebuilding is the fallback for a history that has no system turn yet
        (turn one, or a chat predating stored system turns).
        """
        for message in reversed(self.conversation_history):
            if message.get("role") == "system":
                return message.get("content") or ""
        if self.username and self.session_data is not None:
            return self._build_system_text()
        return ""

    def _max_tokens(self, streaming: bool) -> int:
        ceiling = self.MAX_OUTPUT_TOKENS.get(self.model, self.DEFAULT_MAX_OUTPUT_TOKENS)
        return ceiling if streaming else min(
            ceiling, self.NON_STREAMING_MAX_OUTPUT_TOKENS
        )

    @staticmethod
    def _refusal_text(response) -> str | None:
        """Claude Opus 5 and Fable 5 can decline via safety classifiers: HTTP 200,
        stop_reason "refusal", and an empty or partial content list."""
        if getattr(response, "stop_reason", None) != "refusal":
            return None
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        suffix = f" (category: {category})" if category else ""
        return (
            "Claude declined this request via its safety classifiers"
            f"{suffix}. Try rephrasing, or switch models in the selector."
        )

    def _system_param(self, system_text: str):
        if not system_text:
            return NOT_GIVEN
        return [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _api_messages(self, new_user_message: str | None = None):
        """History as Claude messages. System turns are excluded — they are
        delivered via the `system` parameter, not as conversation.

        Refused turns are excluded too, along with the prompt that triggered
        them: replaying content a safety classifier already declined tends to
        trip the same classifier again on the following turn. The pair stays in
        the database so the UI still shows what happened.
        """
        msgs = []
        for m in self.conversation_history:
            if m.get("role") not in ("user", "assistant"):
                continue
            if m.get("refusal"):
                if msgs and msgs[-1]["role"] == "user":
                    msgs.pop()
                continue
            msgs.append({"role": m["role"], "content": m["content"]})
        if new_user_message is not None:
            msgs.append({"role": "user", "content": new_user_message})
        return msgs

    @staticmethod
    def _usage_from_response(response) -> dict[str, int]:
        """Anthropic reports input_tokens as the *uncached remainder*, so the
        full prompt is that plus whatever was written to and read from cache.
        Reporting input_tokens alone understates the prompt once caching works.
        """
        usage = getattr(response, "usage", None)
        if not usage:
            return {"prompt": 0, "response": 0, "cached": 0}
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        return {
            "prompt": (getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write,
            "response": getattr(usage, "output_tokens", 0) or 0,
            "cached": cache_read,
        }

    def _update_usage(self, response):
        usage = self._usage_from_response(response)
        self.usage_stats["prompt"] += usage["prompt"]
        self.usage_stats["response"] += usage["response"]
        self.usage_stats["cached"] += usage["cached"]
        self.usage_stats["total"] += usage["prompt"] + usage["response"]

    def get_usage_stats(self):
        return self.usage_stats

    async def _stream_message_response(
        self, messages, system_text: str = ""
    ) -> AsyncIterator[dict[str, Any]]:
        text = ""
        final_message = None
        async with self.client.messages.stream(
            model=self.model,
            system=self._system_param(system_text),
            messages=messages,
            max_tokens=self._max_tokens(streaming=True),
        ) as stream:
            async for delta in stream.text_stream:
                if delta:
                    text += str(delta)
                    yield {"type": "delta", "text": str(delta)}
            final_message = await stream.get_final_message()

        sources = []
        citations = getattr(final_message, "citations", None)
        if citations:
            for citation in citations:
                url = getattr(citation, "url", None)
                if url:
                    sources.append(
                        {
                            "link": url,
                            "title": getattr(citation, "title", url),
                        }
                    )

        usage = self._usage_from_response(final_message)
        refusal = self._refusal_text(final_message)
        if refusal:
            text = f"{text}\n\n{refusal}".strip() if text else refusal
        yield {
            "type": "final",
            "text": text or "(No content)",
            "sources": sources,
            "usage": usage,
            "refusal": bool(refusal),
            "response": final_message,
        }

    async def generate_chat_title(self, prompt: str) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Write a concise title for this Autumn insights chat. "
                        "Return only the title, with no quotes, markdown, or trailing punctuation.\n\n"
                        f"{prompt}"
                    ),
                }
            ],
            max_tokens=40,
        )
        text = ""
        if resp and resp.content:
            for block in resp.content:
                block_text = getattr(block, "text", "")
                if block_text:
                    text += str(block_text)
        return text

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data without exposing it in user-visible chat history"""
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        # The payload lives in `system`, so the update turn only has to say that
        # it changed — resending the data inline would duplicate it.
        update_prompt = self._build_system_text(
            self.update_session_data_notice.format(username=self.username)
        )
        msgs = self._api_messages(new_user_message=user_prompt)

        resp = None
        sources = []
        was_refused = False
        try:
            resp = await self.client.messages.create(
                model=self.model,
                system=self._system_param(update_prompt),
                messages=msgs,
                max_tokens=self._max_tokens(streaming=False),
            )

            text = ""
            if resp and resp.content:
                for block in resp.content:
                    block_text = getattr(block, "text", "")
                    if block_text:
                        text += str(block_text)
                if not text:
                    text = "(No content)"
            else:
                text = "(No content)"

            refusal = self._refusal_text(resp)
            if refusal:
                was_refused = True
                text = (
                    refusal
                    if text == "(No content)"
                    else f"{text}\n\n{refusal}"
                )

            citations = getattr(resp, "citations", None)
            if citations:
                for citation in citations:
                    url = getattr(citation, "url", None)
                    if url:
                        sources.append(
                            {
                                "link": url,
                                "title": getattr(citation, "title", url),
                            }
                        )
        except Exception as e:
            text = f"Claude error: {e}"
            resp = None

        # Store update prompt as system (hidden from UI), user prompt separately (visible)
        self.conversation_history.append(
            {"role": "system", "content": update_prompt}
        )
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": sources,
                "model": self.model,
                "usage": self._usage_from_response(resp),
                "refusal": was_refused,
            }
        )

        if resp:
            self._update_usage(resp)
        return text

    async def stream_update_session_data(
        self, sessions_data, user_prompt
    ) -> AsyncIterator[str]:
        """Update session data and stream the assistant response."""
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        update_prompt = self._build_system_text(
            self.update_session_data_notice.format(username=self.username)
        )
        msgs = self._api_messages(new_user_message=user_prompt)

        result = None
        try:
            async for event in self._stream_message_response(msgs, update_prompt):
                if event.get("type") == "delta":
                    yield event.get("text", "")
                elif event.get("type") == "final":
                    result = event
        except Exception as e:
            result = {
                "text": f"Claude error: {e}",
                "sources": [],
                "usage": {"prompt": 0, "response": 0, "cached": 0},
                "response": None,
            }
            yield result["text"]

        self.conversation_history.append({"role": "system", "content": update_prompt})
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": result["text"],
                "sources": result.get("sources", []),
                "model": self.model,
                "usage": result.get("usage", {"prompt": 0, "response": 0, "cached": 0}),
                "refusal": bool(result.get("refusal")),
            }
        )
        if result.get("response"):
            self._update_usage(result["response"])

    async def send_message(self, message) -> str:
        system_text = self._active_system_text()
        if not any(m.get("role") == "system" for m in self.conversation_history):
            # Stored so a resumed chat can recover it — a fresh handler on turn 2+
            # never calls initialize_chat and has no session data of its own.
            self.conversation_history.append(
                {"role": "system", "content": system_text}
            )
        msgs = self._api_messages(new_user_message=message)

        resp = None
        sources = []
        was_refused = False
        try:
            resp = await self.client.messages.create(
                model=self.model,
                system=self._system_param(system_text),
                messages=msgs,
                max_tokens=self._max_tokens(streaming=False),
            )

            text = ""
            if resp and resp.content:
                for block in resp.content:
                    block_text = getattr(block, "text", "")
                    if block_text:
                        text += str(block_text)
                if not text:
                    text = "(No content)"
            else:
                text = "(No content)"

            refusal = self._refusal_text(resp)
            if refusal:
                was_refused = True
                text = (
                    refusal
                    if text == "(No content)"
                    else f"{text}\n\n{refusal}"
                )

            # Extract sources from web search if available
            # Claude may include citations in the response metadata or blocks
            citations = getattr(resp, "citations", None)
            if citations:
                for citation in citations:
                    url = getattr(citation, "url", None)
                    if url:
                        sources.append(
                            {
                                "link": url,
                                "title": getattr(citation, "title", url),
                            }
                        )
        except Exception as e:
            text = f"Claude error: {e}"
            resp = None

        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": sources,
                "model": self.model,
                "usage": self._usage_from_response(resp),
                "refusal": was_refused,
            }
        )

        if resp:
            self._update_usage(resp)
        return text

    async def stream_message(self, message) -> AsyncIterator[str]:
        """Send a message to Claude and stream response text chunks."""
        system_text = self._active_system_text()
        if not any(m.get("role") == "system" for m in self.conversation_history):
            self.conversation_history.append(
                {"role": "system", "content": system_text}
            )
        msgs = self._api_messages(new_user_message=message)

        result = None
        try:
            async for event in self._stream_message_response(msgs, system_text):
                if event.get("type") == "delta":
                    yield event.get("text", "")
                elif event.get("type") == "final":
                    result = event
        except Exception as e:
            result = {
                "text": f"Claude error: {e}",
                "sources": [],
                "usage": {"prompt": 0, "response": 0, "cached": 0},
                "response": None,
            }
            yield result["text"]

        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": result["text"],
                "sources": result.get("sources", []),
                "model": self.model,
                "usage": result.get("usage", {"prompt": 0, "response": 0, "cached": 0}),
                "refusal": bool(result.get("refusal")),
            }
        )
        if result.get("response"):
            self._update_usage(result["response"])

    def get_conversation_history(self) -> list:
        return self.conversation_history
