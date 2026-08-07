from toon import encode
from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch
from typing import Any, AsyncIterator
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class GeminiHandler(BaseLLMHandler):
    """Handler for Google's Gemini API"""

    def __init__(self, model="gemini-2.5-flash", api_key: str | None = None):
        self.model = model
        if not api_key:
            raise RuntimeError("Gemini API key is not configured.")
        self.api_key = api_key
        self.client = genai.Client(api_key=self.api_key)
        self.google_search_tool = Tool(google_search=GoogleSearch())
        self.chat = None

        self.username = None
        self.session_data = None
        self.conversation_history = []

        # Track cumulative usage stats
        self.usage_stats = {"prompt": 0, "response": 0, "cached": 0, "total": 0}

        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.
        You have access to google search to find more information if needed.

        When formatting text and links please use markdown formatting.

        Sessions data:
        {session_data}
        """

        self.update_session_data_notice = """
        {username} has updated their session data.
        Refer to the new session data for the remainder of the conversation.
        """

    def _build_system_text(self, notice: str = "") -> str:
        body = self.system_prompt_template.format(
            username=self.username, session_data=self.session_data
        )
        return f"{notice.strip()}\n{body}" if notice.strip() else body

    def _active_system_text(self) -> str:
        """The system instruction for this request.

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

    async def _create_chat(self, model, history=None, system_text=None):
        """Helper to (re)create a chat for a given model.

        System turns are lifted out of the transcript into system_instruction:
        replaying them as user turns (the previous behaviour) both misrepresents
        the role and pushes the session payload into the cache-varying part of
        the prompt.
        """
        gemini_history = []
        history = history if history is not None else self.conversation_history
        if system_text is None:
            system_text = self._active_system_text()
        if history:
            for m in history:
                if m["role"] == "system":
                    continue
                role = "user" if m["role"] == "user" else "model"
                gemini_history.append({"role": role, "parts": [{"text": m["content"]}]})

        self.chat = self.client.aio.chats.create(
            model=model,
            history=gemini_history,
            config=GenerateContentConfig(
                system_instruction=system_text or None,
                tools=[self.google_search_tool],
                response_modalities=["TEXT"],
            ),
        )
        self.model = model

    @staticmethod
    def _usage_from_response(response) -> dict[str, int]:
        """Unlike Anthropic, Google's prompt_token_count already includes the
        implicitly-cached prefix, so `cached` here is a subset of `prompt`."""
        metadata = getattr(response, "usage_metadata", None)
        if not metadata:
            return {"prompt": 0, "response": 0, "cached": 0}
        return {
            "prompt": getattr(metadata, "prompt_token_count", 0) or 0,
            "response": (getattr(metadata, "candidates_token_count", 0) or 0)
            + (getattr(metadata, "thoughts_token_count", 0) or 0),
            "cached": getattr(metadata, "cached_content_token_count", 0) or 0,
        }

    def _update_usage(self, response):
        """Internal helper to extract and accumulate token usage metadata if available."""
        metadata = getattr(response, "usage_metadata", None)
        if metadata:
            usage = self._usage_from_response(response)
            total_tokens = (
                getattr(metadata, "total_token_count", usage["prompt"] + usage["response"])
                or 0
            )
            self.usage_stats["prompt"] += usage["prompt"]
            self.usage_stats["response"] += usage["response"]
            self.usage_stats["cached"] += usage["cached"]
            self.usage_stats["total"] += total_tokens
        else:
            # Fallback approximation: word count heuristic for total
            # Only approximate incremental tokens for the assistant response
            last_assistant = (
                self.conversation_history[-1]["content"]
                if self.conversation_history
                and self.conversation_history[-1]["role"] == "assistant"
                else ""
            )
            approx = len(str(last_assistant).split())
            self.usage_stats["response"] += approx
            self.usage_stats["total"] += approx

    def get_usage_stats(self):
        """Return cumulative usage stats dict."""
        return self.usage_stats

    def initialize_chat(self, username, sessions_data):
        """Initialize a new chat with username and session data"""
        self.username = username
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )

    def _parse_error(self, e):
        """Attempt to extract structured data from the Gemini error."""
        raw = str(e)
        parsed = {
            "raw": raw,
            "code": None,
            "status": None,
            "message": raw,
            "retry_delay_seconds": None,
            "quota_metrics": [],
        }
        # Heuristic: find first JSON object
        import re, json as _json

        match = re.search(r"(\{\"error\".*)", raw)
        if match:
            json_part = match.group(1)
            try:
                data = _json.loads(json_part)
                err = data.get("error", {})
                parsed["code"] = err.get("code")
                parsed["status"] = err.get("status")
                parsed["message"] = err.get("message", raw)
                details = err.get("details", [])
                for d in details:
                    if d.get("@type", "").endswith("RetryInfo"):
                        # retryDelay like '48s'
                        retry = d.get("retryDelay", "0s")
                        try:
                            parsed["retry_delay_seconds"] = int(retry.replace("s", ""))
                        except Exception:
                            pass
                    if d.get("@type", "").endswith("QuotaFailure"):
                        violations = d.get("violations", [])
                        for v in violations:
                            parsed["quota_metrics"].append(
                                {
                                    "metric": v.get("quotaMetric"),
                                    "id": v.get("quotaId"),
                                    "dimensions": v.get("quotaDimensions", {}),
                                }
                            )
            except Exception:
                pass
        return parsed

    def _handle_error(self, e, original_message=None, allow_fallback=True):
        info = self._parse_error(e)
        is_quota = info["code"] == 429 or (info["status"] == "RESOURCE_EXHAUSTED")
        retry_secs = info.get("retry_delay_seconds")
        assistant_text = []

        if is_quota:
            assistant_text.append(
                "Rate limit or quota exhausted for model: %s." % self.model
            )
            if retry_secs:
                assistant_text.append("Suggested retry after ~%s seconds." % retry_secs)
        else:
            assistant_text.append("An error occurred communicating with Gemini.")

        assistant_text.append("Details: %s" % info["message"])
        if info["quota_metrics"]:
            assistant_text.append("Quota metrics involved:")
            for m in info["quota_metrics"]:
                assistant_text.append(
                    " - %s (%s) dims=%s" % (m["metric"], m["id"], m["dimensions"])
                )
        assistant_text.append(
            "You can monitor usage at https://ai.dev/usage?tab=rate-limit and adjust plan if needed."
        )

        final_message = "\n".join(assistant_text)
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": final_message,
                "error": True,
                "model": self.model,
            }
        )
        return final_message

    def _extract_sources(self, response):
        """Safely extract grounding web sources from a Gemini response.
        Returns a list of dicts with keys: link, title.
        Handles cases where candidates, grounding_metadata or grounding_chunks are missing/None.
        """
        sources = []
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return sources
        first = candidates[0]
        grounding_metadata = getattr(first, "grounding_metadata", None)
        if not grounding_metadata:
            return sources
        grounding_chunks = getattr(grounding_metadata, "grounding_chunks", None)
        if not grounding_chunks:
            return sources
        for chunk in grounding_chunks:
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None):
                title = (getattr(web, "title", "") or "").strip()
                sources.append({"link": web.uri, "title": title})
        return sources

    async def _stream_chat_response(self, prompt) -> AsyncIterator[dict[str, Any]]:
        stream = await self.chat.send_message_stream(prompt)
        chunks = []
        last_response = None
        async for response in stream:
            last_response = response
            delta = getattr(response, "text", "") or ""
            if delta:
                chunks.append(delta)
                yield {"type": "delta", "text": delta}
        usage = self._usage_from_response(last_response)
        yield {
            "type": "final",
            "text": "".join(chunks),
            "sources": self._extract_sources(last_response),
            "usage": usage,
            "response": last_response,
        }

    async def generate_chat_title(self, prompt: str) -> str:
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=GenerateContentConfig(response_modalities=["TEXT"]),
        )
        return getattr(response, "text", "") or ""

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data without adding to chat history"""
        # Update stored session data
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        # The payload lives in system_instruction, which is fixed at chat
        # creation — rebuild the chat so the new data takes effect.
        update_session_data_prompt = self._build_system_text(
            self.update_session_data_notice.format(username=self.username)
        )
        history_before = list(self.conversation_history)
        self.conversation_history.append(
            {"role": "system", "content": update_session_data_prompt}
        )
        self.conversation_history.append({"role": "user", "content": user_prompt})

        try:
            await self._create_chat(
                self.model,
                history=history_before,
                system_text=update_session_data_prompt,
            )

            if not self.chat:
                raise RuntimeError("Chat not initialized")
            response = await self.chat.send_message(user_prompt)
        except Exception as e:
            return self._handle_error(
                e, original_message=update_session_data_prompt, allow_fallback=True
            )

        assistant_response = response.text
        # Safely extract sources (defensive against missing grounding metadata)
        sources = self._extract_sources(response)

        # System and user turns were appended before the call; only the
        # assistant reply is outstanding.
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": assistant_response,
                "sources": sources,
                "model": self.model,
                "usage": self._usage_from_response(response),
            }
        )

        # Update usage stats after assistant response appended
        self._update_usage(response)

        return str(assistant_response)

    async def stream_update_session_data(
        self, sessions_data, user_prompt
    ) -> AsyncIterator[str]:
        """Update session data and stream the assistant response."""
        result = None
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        update_session_data_prompt = self._build_system_text(
            self.update_session_data_notice.format(username=self.username)
        )
        history_before = list(self.conversation_history)
        self.conversation_history.append(
            {"role": "system", "content": update_session_data_prompt}
        )
        self.conversation_history.append({"role": "user", "content": user_prompt})

        try:
            await self._create_chat(
                self.model,
                history=history_before,
                system_text=update_session_data_prompt,
            )

            if not self.chat:
                result = {
                    "text": "Error: Chat not initialized",
                    "sources": [],
                    "usage": {"prompt": 0, "response": 0, "cached": 0},
                    "response": None,
                }
                yield result["text"]
            else:
                async for event in self._stream_chat_response(user_prompt):
                    if event.get("type") == "delta":
                        yield event.get("text", "")
                    elif event.get("type") == "final":
                        result = event
        except Exception as e:
            error_text = self._handle_error(
                e, original_message=update_session_data_prompt, allow_fallback=True
            )
            yield error_text
            return

        result = result or {
            "text": "",
            "sources": [],
            "usage": {"prompt": 0, "response": 0, "cached": 0},
            "response": None,
        }
        # System and user turns were appended before the call; only the
        # assistant reply is outstanding.
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": result["text"],
                "sources": result.get("sources", []),
                "model": self.model,
                "usage": result.get("usage", {"prompt": 0, "response": 0, "cached": 0}),
            }
        )
        if result.get("response"):
            self._update_usage(result["response"])

    async def send_message(self, message) -> str:
        """Send a message to the LLM and return the response"""
        # Same ordering rule as stream_message: this turn's system and user
        # entries land before anything that can raise.
        system_text = self._active_system_text()
        history_before = list(self.conversation_history)
        if not any(m.get("role") == "system" for m in self.conversation_history):
            # Stored so a resumed chat can recover it — a fresh handler on
            # turn 2+ never calls initialize_chat.
            self.conversation_history.append(
                {"role": "system", "content": system_text}
            )
        self.conversation_history.append({"role": "user", "content": message})

        try:
            if not self.chat:
                await self._create_chat(
                    self.model, history=history_before, system_text=system_text
                )

            if not self.chat:
                raise RuntimeError("Chat not initialized")

            try:
                response = await self.chat.send_message(message)
            except Exception as e:
                return self._handle_error(
                    e, original_message=message, allow_fallback=True
                )

            # Extract response text
            assistant_response = response.text
            # Safely extract sources (defensive against missing grounding metadata)
            sources = self._extract_sources(response)

            # Add assistant response to our conversation history
            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": assistant_response,
                    "sources": sources,
                    "model": self.model,
                    "usage": self._usage_from_response(response),
                }
            )

            # Update usage stats
            self._update_usage(response)

            return str(assistant_response)
        except Exception as e:
            # Catch any unexpected formatting/parsing errors
            return self._handle_error(e, original_message=message, allow_fallback=False)

    async def stream_message(self, message) -> AsyncIterator[str]:
        """Send a message to Gemini and stream response text chunks."""
        # Store this turn's system and user entries before anything that can
        # raise. _handle_error only appends an assistant turn, so bailing out
        # earlier used to leave the history short — and the view persists a
        # fixed-size tail, which then re-saved the *previous* exchange and lost
        # the current snapshot.
        system_text = self._active_system_text()
        history_before = list(self.conversation_history)
        if not any(m.get("role") == "system" for m in self.conversation_history):
            self.conversation_history.append(
                {"role": "system", "content": system_text}
            )
        self.conversation_history.append({"role": "user", "content": message})

        try:
            if not self.chat:
                await self._create_chat(
                    self.model, history=history_before, system_text=system_text
                )

            if not self.chat:
                raise RuntimeError("Chat not initialized")

            result = None
            async for event in self._stream_chat_response(message):
                if event.get("type") == "delta":
                    yield event.get("text", "")
                elif event.get("type") == "final":
                    result = event

            result = result or {
                "text": "",
                "sources": [],
                "usage": {"prompt": 0, "response": 0, "cached": 0},
                "response": None,
            }
            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": result["text"],
                    "sources": result.get("sources", []),
                    "model": self.model,
                    "usage": result.get("usage", {"prompt": 0, "response": 0, "cached": 0}),
                }
            )
            if result.get("response"):
                self._update_usage(result["response"])
        except Exception as e:
            error_text = self._handle_error(
                e, original_message=message, allow_fallback=False
            )
            yield error_text

    def get_conversation_history(self) -> list:
        """Return standardized conversation history"""
        return self.conversation_history
