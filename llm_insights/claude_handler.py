from toon import encode
from anthropic import AsyncAnthropic
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class ClaudeHandler(BaseLLMHandler):
    def __init__(self, model="claude-3-5-sonnet-latest", api_key: str | None = None):
        self.model = model
        self.api_key = api_key
        self.client = (
            AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
        )  # falls back to ANTHROPIC_API_KEY env
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
            pt = getattr(usage, "input_tokens", 0)
            ct = getattr(usage, "output_tokens", 0)
            self.usage_stats["prompt"] += pt
            self.usage_stats["response"] += ct
            self.usage_stats["total"] += pt + ct

    def get_usage_stats(self):
        return self.usage_stats

    async def update_session_data(self, sessions_data, user_prompt) -> str:
        self.session_data = encode(
            build_project_json_from_sessions(sessions_data, autumn_compatible=True)
        )
        prompt = self.update_session_data_template.format(
            username=self.username,
            user_prompt=user_prompt,
            session_data=self.session_data,
        )
        return await self.send_message(prompt)

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
            # Also store the actual user message separately for display purposes
            self.conversation_history.append({"role": "user", "content": message})

        # Rebuild history as Claude messages
        # Claude API: system prompt content goes in first user message, then user/assistant pairs
        for m in self.conversation_history:
            if m["role"] == "system":
                # For Claude, include system content in the first user message
                # We'll prepend it to the first user message
                continue
            elif m["role"] == "assistant":
                msgs.append({"role": "assistant", "content": m["content"]})
            elif m["role"] == "user":
                msgs.append({"role": "user", "content": m["content"]})

        # If this is the first message, prepend system prompt to the first user message
        if len(msgs) == 1 and msgs[0]["role"] == "user":
            system_content = self.conversation_history[0]["content"]
            # The system prompt already includes the user message, so we can use it directly
            msgs[0]["content"] = system_content

        # Add the current user message if it's not the first message
        if len(self.conversation_history) > 1:  # More than just system prompt
            msgs.append({"role": "user", "content": message})

        resp = None
        sources = []
        try:
            # Claude standard API does not have a "web_search" parameter.
            # If you have a custom implementation or specific model that supports it,
            # it would usually be via tools. Removing it for standard compatibility.
            resp = await self.client.messages.create(
                model=self.model,
                messages=msgs,
                max_tokens=1024,
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

        # Store user message and assistant response in conversation history
        # User message already stored if first message, otherwise store it now
        if len(self.conversation_history) > 1:  # Not the first message
            self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": text,
                "sources": sources,
                "model": self.model,
            }
        )

        if resp:
            self._update_usage(resp)
        return text

    def get_conversation_history(self) -> list:
        return self.conversation_history
