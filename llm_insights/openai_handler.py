from toon import encode
from openai import OpenAI
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class OpenAIHandler(BaseLLMHandler):
    def __init__(self, model="gpt-5-mini", api_key: str | None = None):
        self.model = model
        self.api_key = api_key
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()  # falls back to env var OPENAI_API_KEY
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
        
        When formating text and links please use markdown formatting.
        
        Here is {username}'s prompt:
        {user_prompt}
        
        New sessions data:
        {session_data}
        """
    def initialize_chat(self, username, sessions_data):
        self.username = username
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))
    def _update_usage(self, response):
        usage = getattr(response, 'usage', None)
        if usage:
            pt = getattr(usage, 'prompt_tokens', 0)
            ct = getattr(usage, 'completion_tokens', 0)
            tt = getattr(usage, 'total_tokens', pt+ct)
            self.usage_stats['prompt'] += pt
            self.usage_stats['response'] += ct
            self.usage_stats['total'] += tt
    def get_usage_stats(self):
        return self.usage_stats
    def update_session_data(self, sessions_data, user_prompt):
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))
        prompt = self.update_session_data_template.format(username=self.username, user_prompt=user_prompt, session_data=self.session_data)
        return self.send_message(prompt)
    def send_message(self, message):
        msgs = []
        
        # If this is the first message, create and store system prompt
        if len(self.conversation_history) == 0:
            system_prompt = self.system_prompt_template.format(
                username=self.username,
                user_prompt=message,
                session_data=self.session_data
            )
            # Store system prompt in conversation history first
            self.conversation_history.append({"role": "system", "content": system_prompt})
        
        # Rebuild history as OpenAI messages (system+user+assistant)
        for m in self.conversation_history:
            role = m['role'] if m['role'] in ['user','assistant','system'] else 'user'
            msgs.append({"role": role, "content": m['content']})
        
        # Add the current user message
        msgs.append({"role": "user", "content": message})
        
        resp = None
        try:
            resp = self.client.chat.completions.create(model=self.model, messages=msgs)
            text = resp.choices[0].message.content
        except Exception as e:
            text = f"OpenAI error: {e}"
        
        # Store user message and assistant response in conversation history
        self.conversation_history.append({"role": "user", "content": message})
        self.conversation_history.append({"role": "assistant", "content": text, "model": self.model})
        
        if resp:
            self._update_usage(resp)
        return text
    def get_conversation_history(self):
        return self.conversation_history

