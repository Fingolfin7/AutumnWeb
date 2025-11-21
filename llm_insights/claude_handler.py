from toon import encode
from anthropic import Anthropic
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class ClaudeHandler(BaseLLMHandler):
    def __init__(self, model="claude-3-5-sonnet-latest", api_key: str | None = None):
        self.model = model
        self.api_key = api_key
        self.client = Anthropic(api_key=api_key) if api_key else Anthropic()  # falls back to ANTHROPIC_API_KEY env
        self.username = None
        self.session_data = None
        self.conversation_history = []
        self.usage_stats = {"prompt": 0, "response": 0, "total": 0}
        self.system_prompt_template = """
        You are an expert project and time tracking analyst.
        User: {username}
        Prompt: {user_prompt}
        Session Data: {session_data}
        Cite session notes and times. Use markdown.
        """
        self.update_session_data_template = """
        Updated session data for {username}:
        {session_data}
        Prompt: {user_prompt}
        Adjust insights accordingly.
        """
    def initialize_chat(self, username, sessions_data):
        self.username = username
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))
    def _update_usage(self, response):
        usage = getattr(response, 'usage', None)
        if usage:
            pt = getattr(usage, 'input_tokens', 0)
            ct = getattr(usage, 'output_tokens', 0)
            self.usage_stats['prompt'] += pt
            self.usage_stats['response'] += ct
            self.usage_stats['total'] += pt + ct
    def get_usage_stats(self):
        return self.usage_stats
    def update_session_data(self, sessions_data, user_prompt):
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))
        prompt = self.update_session_data_template.format(username=self.username, user_prompt=user_prompt, session_data=self.session_data)
        return self.send_message(prompt)
    def send_message(self, message):
        if len(self.conversation_history) == 0:
            initial = self.system_prompt_template.format(username=self.username, user_prompt=message, session_data=self.session_data)
            user_content = initial
        else:
            user_content = message
        msgs = []
        for m in self.conversation_history:
            if m['role'] == 'assistant':
                msgs.append({"role": "assistant", "content": m['content']})
            elif m['role'] == 'user':
                msgs.append({"role": "user", "content": m['content']})
        msgs.append({"role": "user", "content": user_content})
        try:
            resp = self.client.messages.create(model=self.model, messages=msgs, max_tokens=1024)
            text = resp.content[0].text if resp.content else "(No content)"
        except Exception as e:
            text = f"Claude error: {e}"
            resp = None
        if len(self.conversation_history) == 0:
            self.conversation_history.append({"role": "system", "content": user_content})
        else:
            self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": text, "model": self.model})
        if resp:
            self._update_usage(resp)
        return text
    def get_conversation_history(self):
        return self.conversation_history

