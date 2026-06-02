from typing import Any

from openai import AsyncOpenAI
from toon import encode

from core.utils import build_project_json_from_sessions
from users.codex_auth import CODEX_CHATGPT_BASE_URL

from .base_handler import BaseLLMHandler


class OpenAIHandler(BaseLLMHandler):
    AUTH_API = "api"
    AUTH_CODEX = "codex"
    AUTH_CODEX_WITH_API_FALLBACK = "codex_with_api_fallback"

    def __init__(
        self,
        model="gpt-5.5",
        api_key: str | None = None,
        codex_token: str | None = None,
        auth_mode: str | None = None,
        reasoning_effort: str | None = "medium",
    ):
        self.model = model
        self.api_key = api_key
        self.codex_token = codex_token
        self.reasoning_effort = reasoning_effort
        self.auth_mode = auth_mode or self._default_auth_mode()
        self.api_client = None
        self.codex_client = (
            AsyncOpenAI(api_key=codex_token, base_url=CODEX_CHATGPT_BASE_URL)
            if codex_token
            else None
        )
        self.username = None
        self.session_data = None
        self.conversation_history = []
        self.usage_stats = {"prompt": 0, "response": 0, "total": 0}
        self.last_auth_source = self.auth_mode
        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.
        You have access to web search to find more information if needed.

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
        You have access to web search to find more information if needed.

        When formatting text and links please use markdown formatting.

        Here is {username}'s prompt:
        {user_prompt}

        New sessions data:
        {session_data}
        """

    def _default_auth_mode(self) -> str:
        if self.codex_token and self.api_key:
            return self.AUTH_CODEX_WITH_API_FALLBACK
        if self.codex_token:
            return self.AUTH_CODEX
        return self.AUTH_API

    def initialize_chat(self, username, sessions_data):
        self.username = username
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )

    def get_usage_stats(self):
        return self.usage_stats

    def set_conversation_history(self, history: list):
        self.conversation_history = history

    def _messages_from_history(self):
        return [
            {
                "role": m["role"] if m["role"] in ["user", "assistant", "system"] else "user",
                "content": m["content"],
            }
            for m in self.conversation_history
        ]

    def _api_response_kwargs(self, messages):
        kwargs = {
            "model": self.model,
            "input": messages,
            "tools": [{"type": "web_search"}],
            "include": ["web_search_call.action.sources"],
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs

    def _codex_response_kwargs(self, messages, include_web_search=True):
        instructions = next((m["content"] for m in messages if m["role"] == "system"), "")
        input_messages = [m for m in messages if m["role"] != "system"]
        kwargs = {
            "model": self.model,
            "instructions": instructions,
            "input": self._codex_input(input_messages),
            "max_output_tokens": 4096,
            "store": False,
        }
        if self.reasoning_effort in {"low", "medium", "high"}:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        if include_web_search:
            kwargs["tools"] = [{"type": "web_search"}]
            kwargs["include"] = ["web_search_call.action.sources"]
        return kwargs

    def _codex_input(self, messages):
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

    async def _send_api(self, messages) -> dict[str, Any]:
        resp = await self._api_client().responses.create(
            **self._api_response_kwargs(messages)
        )
        text = self._response_text(resp)
        sources = self._extract_sources(resp)
        usage = self._usage_from_api_response(resp)
        return {"text": text, "sources": sources, "usage": usage, "source": "api_key"}

    def _api_client(self):
        if self.api_client is None:
            self.api_client = (
                AsyncOpenAI(api_key=self.api_key)
                if self.api_key
                else AsyncOpenAI()
            )
        return self.api_client

    async def _send_codex(self, messages) -> dict[str, Any]:
        if self.codex_client is None:
            raise RuntimeError("Codex auth is not configured.")

        kwargs = self._codex_response_kwargs(messages, include_web_search=True)
        try:
            return await self._stream_codex(kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            fallback = dict(kwargs)
            if "unsupported parameter: tools" in msg or "unsupported parameter: include" in msg:
                fallback.pop("tools", None)
                fallback.pop("include", None)
                return await self._stream_codex(fallback)
            if "unsupported parameter: max_output_tokens" in msg:
                fallback.pop("max_output_tokens", None)
                return await self._stream_codex(fallback)
            if "unsupported parameter: reasoning" in msg:
                fallback.pop("reasoning", None)
                return await self._stream_codex(fallback)
            raise

    async def _stream_codex(self, kwargs):
        request = dict(kwargs)
        request["stream"] = True
        event_stream = await self.codex_client.responses.create(**request)
        chunks = []
        usage = {"prompt": 0, "response": 0}
        sources = []
        async for event in event_stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if isinstance(delta, str) and delta:
                    chunks.append(delta)
            elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
                usage = self._usage_from_codex_event(event)
                event_sources = self._extract_sources(getattr(event, "response", None))
                if event_sources:
                    sources = event_sources
        return {
            "text": "".join(chunks).strip(),
            "sources": sources,
            "usage": usage,
            "source": "codex",
        }

    async def _send_with_priority(self, messages) -> dict[str, Any]:
        if self.auth_mode == self.AUTH_CODEX:
            result = await self._send_codex(messages)
            self.last_auth_source = "codex"
            return result
        if self.auth_mode == self.AUTH_CODEX_WITH_API_FALLBACK:
            try:
                result = await self._send_codex(messages)
                self.last_auth_source = "codex"
                return result
            except Exception:
                result = await self._send_api(messages)
                self.last_auth_source = "api_key_fallback"
                return result
        result = await self._send_api(messages)
        self.last_auth_source = "api_key"
        return result

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        update_prompt = self.update_session_data_template.format(
            username=self.username,
            user_prompt=user_prompt,
            session_data=self.session_data,
        )
        messages = self._messages_from_history()
        messages.append({"role": "user", "content": update_prompt})

        try:
            result = await self._send_with_priority(messages)
        except Exception as e:
            result = {
                "text": f"OpenAI error: {e}",
                "sources": [],
                "usage": {"prompt": 0, "response": 0},
                "source": self.last_auth_source,
            }

        self.conversation_history.append({"role": "system", "content": update_prompt})
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self._append_assistant_result(result)
        return result["text"]

    async def send_message(self, message) -> str:
        if len(self.conversation_history) == 0:
            system_prompt = self.system_prompt_template.format(
                username=self.username,
                user_prompt=message,
                session_data=self.session_data,
            )
            self.conversation_history.append({"role": "system", "content": system_prompt})

        messages = self._messages_from_history()
        messages.append({"role": "user", "content": message})

        try:
            result = await self._send_with_priority(messages)
        except Exception as e:
            result = {
                "text": f"OpenAI error: {e}",
                "sources": [],
                "usage": {"prompt": 0, "response": 0},
                "source": self.last_auth_source,
            }

        self.conversation_history.append({"role": "user", "content": message})
        self._append_assistant_result(result)
        return result["text"]

    def _append_assistant_result(self, result):
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": result["text"],
                "sources": result.get("sources", []),
                "model": self.model,
                "usage": result.get("usage", {"prompt": 0, "response": 0}),
                "auth_source": result.get("source", self.last_auth_source),
            }
        )
        self._update_usage(result.get("usage", {}))

    def _response_text(self, resp):
        if hasattr(resp, "output_text"):
            return resp.output_text
        text = ""
        for output in getattr(resp, "output", []) or []:
            if getattr(output, "type", None) != "message":
                continue
            for content in getattr(output, "content", []) or []:
                if hasattr(content, "text") and hasattr(content.text, "value"):
                    text += content.text.value
                elif hasattr(content, "text"):
                    text += str(content.text)
        return text or str(resp)

    def _extract_sources(self, resp):
        sources = []
        if resp is None:
            return sources
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "message":
                for part in getattr(item, "content", []) or []:
                    annotations = getattr(part, "annotations", []) or []
                    for ann in annotations:
                        if getattr(ann, "type", None) == "url_citation":
                            url = getattr(ann, "url", None)
                            title = getattr(ann, "title", None) or url
                            if url:
                                sources.append(
                                    {"link": url, "title": title, "kind": "citation"}
                                )
            if getattr(item, "type", None) == "web_search_call":
                action = getattr(item, "action", None)
                for src in getattr(action, "sources", []) or []:
                    url = getattr(src, "url", None)
                    title = getattr(src, "title", None) or url
                    provider = getattr(src, "provider", None)
                    if url:
                        sources.append(
                            {
                                "link": url,
                                "title": title,
                                "provider": provider,
                                "kind": "source",
                            }
                        )

        seen = set()
        unique_sources = []
        for source in sources:
            if source["link"] in seen:
                continue
            seen.add(source["link"])
            unique_sources.append(source)
        return unique_sources

    def _usage_from_api_response(self, response) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if not usage:
            return {"prompt": 0, "response": 0}
        prompt = getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0)) or 0
        response_tokens = (
            getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0)) or 0
        )
        return {"prompt": prompt, "response": response_tokens}

    def _usage_from_codex_event(self, event) -> dict[str, int]:
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

    def get_conversation_history(self) -> list:
        return self.conversation_history
