import json
from toon import encode
from abc import ABC, abstractmethod
from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch
from AutumnWeb.settings import GEMINI_API_KEY
from core.utils import build_project_json_from_sessions


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    @abstractmethod
    def initialize_chat(self, username, sessions_data):
        pass

    @abstractmethod
    def send_message(self, message):
        pass

    @abstractmethod
    def get_conversation_history(self):
        pass
    
    @abstractmethod
    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data the LLM is working with"""
        pass


class GeminiHandler(BaseLLMHandler):
    """Handler for Google's Gemini API"""

    def __init__(self, model="gemini-2.5-flash"):
        self.api_key = GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)
        self.google_search_tool = Tool(
            google_search=GoogleSearch()
        )
        self.chat = self.client.chats.create(model=model,
                                             config=GenerateContentConfig(
                                                 tools=[self.google_search_tool],
                                                 response_modalities=["TEXT"]
                                             ))

        self.username = None
        self.session_data = None

        self.conversation_history = []

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

    def initialize_chat(self, username, sessions_data):
        """Initialize a new chat with username and session data"""
        self.username = username
        self.session_data = encode(build_project_json_from_sessions(sessions_data, autumn_compatible=True))

    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data without adding to chat history"""
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

        assistant_response = response.text
        sources = []
        # check for sources from the Google Search tool
        if response.candidates:
            if response.candidates[0].grounding_metadata.grounding_chunks:
                for chunk in response.candidates[0].grounding_metadata.grounding_chunks:
                    if chunk.web:
                        sources.append({
                            "link": chunk.web.uri,
                            "text": chunk.web.title.strip()
                        })

        # Add message to conversation history
        self.conversation_history.append({"role": "system", "content": update_session_data_prompt})
        self.conversation_history.append({"role": "user", "content": user_prompt}) # display user message
        self.conversation_history.append({"role": "assistant", "content": assistant_response, "sources": sources})

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
                response = self.chat.send_message(initial_prompt)
                self.conversation_history.append({"role": "system", "content": initial_prompt})
                self.conversation_history.append(
                    {"role": "user", "content": message})  # for display purposes, only show what the user sent
            else:
                self.conversation_history.append({"role": "user", "content": message})
                response = self.chat.send_message(message)

            # Extract response text
            assistant_response = response.text
            sources = []
            # check for sources from the Google Search tool
            if response.candidates:
                if response.candidates[0].grounding_metadata.grounding_chunks:
                    for chunk in response.candidates[0].grounding_metadata.grounding_chunks:
                        if chunk.web:
                            sources.append({
                                "link": chunk.web.uri,
                                "title": chunk.web.title.strip()
                            })

            # Add assistant response to our conversation history
            self.conversation_history.append({"role": "assistant", "content": assistant_response, "sources": sources})

            return assistant_response
        except Exception as e:
            error_msg = f"Error communicating with Gemini: {str(e)}"
            self.conversation_history.append({"role": "assistant", "content": error_msg})
            return error_msg

    def get_conversation_history(self):
        """Return standardized conversation history"""
        return self.conversation_history


# Factory function to get the appropriate handler
def get_llm_handler(model=""):
    if "gemini" in model.lower():
        return GeminiHandler(model=model)
    # Add more handlers here as needed
    else:
        raise ValueError(f"Unsupported model provider: {model}")
