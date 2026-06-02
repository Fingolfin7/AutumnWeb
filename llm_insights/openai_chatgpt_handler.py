from typing import Any

from openai import AsyncOpenAI
from toon import encode

from core.utils import build_project_json_from_sessions
from users.codex_auth import CODEX_CHATGPT_BASE_URL

from .base_handler import BaseLLMHandler


class OpenAIChatGPTHandler(BaseLLMHandler):
    def __init__(
        self,
        model="gpt-5-codex",
        bearer_token: str | None = None,
        reasoning_effort: str | None = "medium",
    ):
        self.model = model
        self.bearer_token = bearer_token
        self.reasoning_effort = reasoning_effort
        self.client = AsyncOpenAI(
            api_key=bearer_token or "missing-token",
            base_url=CODEX_CHATGPT_BASE_URL,
        )
        self.username = None
        self.session_data = None
        self.conversation_history = []
        self.usage_stats = {"prompt": 0, "response": 0, "total": 0}
        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.

        When formatting text and links please use markdown formatting.

        Here is {username}'s prompt:
        {user_prompt}

        Sessions data:
        {session_data}
        """
        self.update_session_data_template = """
        {username} has updated their session data.
        Refer to the new session data for the remainder of the conversation.
        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.

        When formatting text and links please use markdown formatting.

        Here is {username}'s prompt:
        {user_prompt}

        New sessions data:
        {session_data}
        """

    def initialize_chat(self, username, sessions_data):
        self.username = username
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )

    def get_usage_stats(self):
        return self.usage_stats

    def set_conversation_history(self, history: list):
        self.conversation_history = history

    def _response_kwargs(self, messages):
        instructions = next((m["content"] for m in messages if m["role"] == "system"), "")
        input_messages = [m for m in messages if m["role"] != "system"]
        kwargs = {
            "model": self.model,
            "instructions": instructions,
            "input": self._build_input(input_messages),
            "max_output_tokens": 4096,
            "store": False,
        }
        if self.reasoning_effort in {"low", "medium", "high"}:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs

    def _build_input(self, messages):
        items = []
        for msg in messages:
            role = "assistant" if msg["role"] == "assistant" else "user"
            text_part_type = "output_text" if role == "assistant" else "input_text"
            items.append(
                {
                    "role": role,
                    "content": [{"type": text_part_type, "text": msg["content"]}],
                }
            )
        return items

    async def _stream_response(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, int]]:
        request = dict(kwargs)
        request["stream"] = True
        try:
            event_stream = await self.client.responses.create(**request)
        except Exception as exc:
            msg = str(exc).lower()
            if "unsupported parameter: max_output_tokens" in msg:
                fallback = dict(kwargs)
                fallback.pop("max_output_tokens", None)
                fallback["stream"] = True
                event_stream = await self.client.responses.create(**fallback)
            elif "unsupported parameter: reasoning" in msg:
                fallback = dict(kwargs)
                fallback.pop("reasoning", None)
                fallback["stream"] = True
                event_stream = await self.client.responses.create(**fallback)
            else:
                raise

        chunks = []
        usage = {"prompt": 0, "response": 0}
        async for event in event_stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if isinstance(delta, str) and delta:
                    chunks.append(delta)
            elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
                event_usage = self._usage_from_event(event)
                usage["prompt"] = event_usage.get("prompt", 0)
                usage["response"] = event_usage.get("response", 0)

        return "".join(chunks).strip(), usage

    def _usage_from_event(self, event) -> dict[str, int]:
        response = getattr(event, "response", None)
        usage = getattr(response, "usage", None) if response else None
        if usage is None:
            return {"prompt": 0, "response": 0}
        if isinstance(usage, dict):
            prompt = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            response_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
            return {"prompt": prompt, "response": response_tokens}
        prompt = getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0
        response_tokens = (
            getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
        )
        return {"prompt": prompt, "response": response_tokens}

    def _update_usage(self, usage):
        self.usage_stats["prompt"] += usage.get("prompt", 0)
        self.usage_stats["response"] += usage.get("response", 0)
        self.usage_stats["total"] = (
            self.usage_stats["prompt"] + self.usage_stats["response"]
        )

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        update_prompt = self.update_session_data_template.format(
            username=self.username,
            user_prompt=user_prompt,
            session_data=self.session_data,
        )

        messages = [
            {
                "role": m["role"] if m["role"] in ["user", "assistant", "system"] else "user",
                "content": m["content"],
            }
            for m in self.conversation_history
        ]
        messages.append({"role": "user", "content": update_prompt})

        try:
            text, usage = await self._stream_response(self._response_kwargs(messages))
        except Exception as e:
            text = f"OpenAI Codex error: {e}"
            usage = {"prompt": 0, "response": 0}

        self.conversation_history.append({"role": "system", "content": update_prompt})
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": [],
                "model": self.model,
                "usage": usage,
            }
        )
        self._update_usage(usage)
        return text

    async def send_message(self, message) -> str:
        if len(self.conversation_history) == 0:
            system_prompt = self.system_prompt_template.format(
                username=self.username,
                user_prompt=message,
                session_data=self.session_data,
            )
            self.conversation_history.append({"role": "system", "content": system_prompt})

        messages = [
            {
                "role": m["role"] if m["role"] in ["user", "assistant", "system"] else "user",
                "content": m["content"],
            }
            for m in self.conversation_history
        ]
        messages.append({"role": "user", "content": message})

        try:
            text, usage = await self._stream_response(self._response_kwargs(messages))
        except Exception as e:
            text = f"OpenAI Codex error: {e}"
            usage = {"prompt": 0, "response": 0}

        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": [],
                "model": self.model,
                "usage": usage,
            }
        )
        self._update_usage(usage)
        return text

    def get_conversation_history(self) -> list:
        return self.conversation_history
