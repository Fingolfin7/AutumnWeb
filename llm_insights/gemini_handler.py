from toon import encode
from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch
from AutumnWeb.settings import GEMINI_API_KEY
from core.utils import build_project_json_from_sessions
from .base_handler import BaseLLMHandler


class GeminiHandler(BaseLLMHandler):
    """Handler for Google's Gemini API"""

    def __init__(self, model="gemini-2.5-flash", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)
        self.google_search_tool = Tool(google_search=GoogleSearch())
        self._create_chat(self.model)

        self.username = None
        self.session_data = None
        self.conversation_history = []

        # Track cumulative usage stats
        self.usage_stats = {"prompt": 0, "response": 0, "total": 0}

        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        All time and duration values are in minutes.
        You have access to google search to find more information if needed.
        
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
        You have access to google search to find more information if needed.
        
        When formating text and links please use markdown formatting.
        
        Here is {username}'s prompt:
        {user_prompt}
        
        New sessions data:
        {session_data}
        """

    def _create_chat(self, model):
        """Helper to (re)create a chat for a given model."""
        self.chat = self.client.chats.create(
            model=model,
            config=GenerateContentConfig(
                tools=[self.google_search_tool],
                response_modalities=["TEXT"]
            )
        )
        self.model = model

    def _update_usage(self, response):
        """Internal helper to extract and accumulate token usage metadata if available."""
        metadata = getattr(response, "usage_metadata", None)
        if metadata:
            # Google response usage metadata fields: prompt_token_count, candidates_token_count, total_token_count
            prompt_tokens = getattr(metadata, "prompt_token_count", 0) or 0
            response_tokens = getattr(metadata, "candidates_token_count", 0) or 0
            total_tokens = getattr(metadata, "total_token_count", prompt_tokens + response_tokens) or 0
            self.usage_stats["prompt"] += prompt_tokens
            self.usage_stats["response"] += response_tokens
            self.usage_stats["total"] += total_tokens
        else:
            # Fallback approximation: word count heuristic for total
            # Only approximate incremental tokens for the assistant response
            last_assistant = self.conversation_history[-1]["content"] if self.conversation_history and self.conversation_history[-1]["role"] == "assistant" else ""
            approx = len(last_assistant.split())
            self.usage_stats["response"] += approx
            self.usage_stats["total"] += approx

    def get_usage_stats(self):
        """Return cumulative usage stats dict."""
        return self.usage_stats

    def initialize_chat(self, username, sessions_data):
        """Initialize a new chat with username and session data"""
        self.username = username
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))

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
        match = re.search(r'(\{"error".*)', raw)
        if match:
            json_part = match.group(1)
            try:
                data = _json.loads(json_part)
                err = data.get('error', {})
                parsed['code'] = err.get('code')
                parsed['status'] = err.get('status')
                parsed['message'] = err.get('message', raw)
                details = err.get('details', [])
                for d in details:
                    if d.get('@type', '').endswith('RetryInfo'):
                        # retryDelay like '48s'
                        retry = d.get('retryDelay', '0s')
                        try:
                            parsed['retry_delay_seconds'] = int(retry.replace('s', ''))
                        except:
                            pass
                    if d.get('@type', '').endswith('QuotaFailure'):
                        violations = d.get('violations', [])
                        for v in violations:
                            parsed['quota_metrics'].append({
                                'metric': v.get('quotaMetric'),
                                'id': v.get('quotaId'),
                                'dimensions': v.get('quotaDimensions', {})
                            })
            except Exception:
                pass
        return parsed

    def _handle_error(self, e, original_message=None, allow_fallback=True):
        info = self._parse_error(e)
        is_quota = info['code'] == 429 or (info['status'] == 'RESOURCE_EXHAUSTED')
        retry_secs = info.get('retry_delay_seconds')
        assistant_text = []

        if is_quota:
            assistant_text.append("Rate limit or quota exhausted for model: %s." % self.model)
            if retry_secs:
                assistant_text.append("Suggested retry after ~%s seconds." % retry_secs)
        else:
            assistant_text.append("An error occurred communicating with Gemini.")

        assistant_text.append("Details: %s" % info['message'])
        if info['quota_metrics']:
            assistant_text.append("Quota metrics involved:")
            for m in info['quota_metrics']:
                assistant_text.append(" - %s (%s) dims=%s" % (m['metric'], m['id'], m['dimensions']))
        assistant_text.append("You can monitor usage at https://ai.dev/usage?tab=rate-limit and adjust plan if needed.")

        final_message = "\n".join(assistant_text)
        self.conversation_history.append({
            "role": "assistant",
            "content": final_message,
            "error": True,
            "model": self.model
        })
        return final_message

    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data without adding to chat history"""
        try:
            if not self.chat:
                return None

            # Update stored session data
            self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))

            # Create a new chat with updated system prompt
            update_session_data_prompt = self.update_session_data_template.format(
                username=self.username,
                user_prompt=user_prompt,
                session_data=self.session_data
            )

            response = self.chat.send_message(update_session_data_prompt)
        except Exception as e:
            return self._handle_error(e, original_message=update_session_data_prompt, allow_fallback=True)

        assistant_response = response.text
        sources = []
        # check for sources from the Google Search tool
        if response.candidates:
            if response.candidates[0].grounding_metadata.grounding_chunks:
                for chunk in response.candidates[0].grounding_metadata.grounding_chunks:
                    if chunk.web:
                        sources.append({"link": chunk.web.uri, "text": chunk.web.title.strip()})

        # Add message to conversation history
        self.conversation_history.append({"role": "system", "content": update_session_data_prompt})
        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append({"role": "assistant", "content": assistant_response, "sources": sources, "model": self.model})

        # Update usage stats after assistant response appended
        self._update_usage(response)

        return assistant_response

    def send_message(self, message):
        """Send a message to the LLM and return the response"""
        try:
            if len(self.conversation_history) == 0:
                # send system prompt along with user message
                initial_prompt = self.system_prompt_template.format(
                    username=self.username,
                    user_prompt=message,
                    session_data=self.session_data
                )
                try:
                    response = self.chat.send_message(initial_prompt)
                except Exception as e:
                    return self._handle_error(e, original_message=initial_prompt, allow_fallback=True)
                self.conversation_history.append({"role": "system", "content": initial_prompt})
                self.conversation_history.append({"role": "user", "content": message})
            else:
                self.conversation_history.append({"role": "user", "content": message})
                try:
                    response = self.chat.send_message(message)
                except Exception as e:
                    return self._handle_error(e, original_message=message, allow_fallback=True)

            # Extract response text
            assistant_response = response.text
            sources = []
            # check for sources from the Google Search tool
            if response.candidates:
                if response.candidates[0].grounding_metadata.grounding_chunks:
                    for chunk in response.candidates[0].grounding_metadata.grounding_chunks:
                        if chunk.web:
                            sources.append({"link": chunk.web.uri, "title": chunk.web.title.strip()})

            # Add assistant response to our conversation history
            self.conversation_history.append({"role": "assistant", "content": assistant_response, "sources": sources, "model": self.model})

            # Update usage stats
            self._update_usage(response)

            return assistant_response
        except Exception as e:
            # Catch any unexpected formatting/parsing errors
            return self._handle_error(e, original_message=message, allow_fallback=False)

    def get_conversation_history(self):
        """Return standardized conversation history"""
        return self.conversation_history

