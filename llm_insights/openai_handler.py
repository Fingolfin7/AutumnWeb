from toon import encode
from openai import AsyncOpenAI
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class OpenAIHandler(BaseLLMHandler):
    def __init__(self, model="gpt-5-mini", api_key: str | None = None):
        self.model = model
        self.api_key = api_key
        self.client = (
            AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()
        )  # falls back to env var OPENAI_API_KEY
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
        You have access to web search to find more information if needed.
        
        When formating text and links please use markdown formatting.
        
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
        
        When formating text and links please use markdown formatting.
        
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

    def _update_usage(self, response):
        usage = getattr(response, "usage", None)
        if usage:
            pt = getattr(usage, "prompt_tokens", 0)
            ct = getattr(usage, "completion_tokens", 0)
            tt = getattr(usage, "total_tokens", pt + ct)
            self.usage_stats["prompt"] += pt
            self.usage_stats["response"] += ct
            self.usage_stats["total"] += tt

    def get_usage_stats(self):
        return self.usage_stats

    def set_conversation_history(self, history: list):
        self.conversation_history = history

    def _extract_sources(self, resp):
        """Extract sources from OpenAI Responses API response"""
        sources = []

        # 1) Inline citations from the assistant message
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", []) or []:
                annotations = getattr(part, "annotations", []) or []
                for ann in annotations:
                    if getattr(ann, "type", None) == "url_citation":
                        url = getattr(ann, "url", None)
                        title = getattr(ann, "title", None) or url
                        if url:
                            sources.append(
                                {
                                    "link": url,
                                    "title": title,
                                    "kind": "citation",
                                }
                            )

        # 2) Full source list from web_search_call.action.sources (if included)
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) != "web_search_call":
                continue
            action = getattr(item, "action", None)
            if not action:
                continue
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

        # De-duplicate by URL while preserving order
        seen = set()
        unique_sources = []
        for s in sources:
            if s["link"] in seen:
                continue
            seen.add(s["link"])
            unique_sources.append(s)

        return unique_sources

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        """Update the session data without exposing it in user-visible chat history"""
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        update_prompt = self.update_session_data_template.format(
            username=self.username,
            user_prompt=user_prompt,
            session_data=self.session_data,
        )

        # Build API messages from existing conversation history
        msgs = []
        for m in self.conversation_history:
            role = m["role"] if m["role"] in ["user", "assistant", "system"] else "user"
            msgs.append({"role": role, "content": m["content"]})

        # Send the full update prompt (with session data) to the API
        msgs.append({"role": "user", "content": update_prompt})

        resp = None
        sources = []
        try:
            resp = await self.client.responses.create(
                model=self.model,
                input=msgs,
                tools=[{"type": "web_search"}],
                include=["web_search_call.action.sources"],
            )
            if hasattr(resp, "output_text"):
                text = resp.output_text
            else:
                text = ""
                if hasattr(resp, "output") and resp.output:
                    for o in resp.output:
                        if o.type == "message":
                            for c in o.content:
                                if hasattr(c, "text") and hasattr(c.text, "value"):
                                    text += c.text.value
                if not text:
                    text = str(resp)

            sources = self._extract_sources(resp)
        except Exception as e:
            text = f"OpenAI error: {e}"

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
                "usage": {
                    "prompt": getattr(resp.usage, "prompt_tokens", 0)
                    if resp and resp.usage
                    else 0,
                    "response": getattr(resp.usage, "completion_tokens", 0)
                    if resp and resp.usage
                    else 0,
                },
            }
        )

        if resp:
            self._update_usage(resp)
        return text

    async def send_message(self, message) -> str:
        msgs = []

        # If this is the first message, create and store system prompt
        if len(self.conversation_history) == 0:
            system_prompt = self.system_prompt_template.format(
                username=self.username,
                user_prompt=message,
                session_data=self.session_data,
            )
            # Store system prompt in conversation history first
            self.conversation_history.append(
                {"role": "system", "content": system_prompt}
            )

        # Rebuild history as OpenAI messages (system+user+assistant)
        for m in self.conversation_history:
            role = m["role"] if m["role"] in ["user", "assistant", "system"] else "user"
            msgs.append({"role": role, "content": m["content"]})

        # Add the current user message
        msgs.append({"role": "user", "content": message})

        resp = None
        sources = []
        try:
            # Enable web search by default using Responses API
            # Include sources in the response
            resp = await self.client.responses.create(
                model=self.model,
                input=msgs,
                tools=[{"type": "web_search"}],
                include=["web_search_call.action.sources"],
            )
            # Extract text from Responses API
            if hasattr(resp, "output_text"):
                text = resp.output_text
            else:
                # Manual extraction if needed
                text = ""
                if hasattr(resp, "output") and resp.output:
                    for o in resp.output:
                        if o.type == "message":
                            for c in o.content:
                                if hasattr(c, "text") and hasattr(c.text, "value"):
                                    text += c.text.value
                if not text:
                    text = str(resp)

            # Extract sources using proper extraction method
            sources = self._extract_sources(resp)
        except Exception as e:
            text = f"OpenAI error: {e}"

        # Store user message and assistant response in conversation history
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": sources,
                "model": self.model,
                "usage": {
                    "prompt": getattr(resp.usage, "prompt_tokens", 0)
                    if resp and resp.usage
                    else 0,
                    "response": getattr(resp.usage, "completion_tokens", 0)
                    if resp and resp.usage
                    else 0,
                },
            }
        )

        if resp:
            self._update_usage(resp)
        return text

    def get_conversation_history(self) -> list:
        return self.conversation_history
