import json
from abc import ABC, abstractmethod
from google import genai
from AutumnWeb import settings


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
    def update_session_data(self, sessions_data):
        """Update the session data the LLM is working with"""
        pass


class GeminiHandler(BaseLLMHandler):
    """Handler for Google's Gemini API"""

    def __init__(self, api_key=None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)
        self.chat = self.client.chats.create(model="gemini-2.0-flash")
        self.conversation_history = []
        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.
        
        When formating text and links please use markdown formatting.

        Sessions data:
        {sessions_data}
        """

        self.update_session_data_template = """
        {username} has updated their session data. 
        Please refer to the new session data for the remainder of the conversation.
        
        New sessions data:
        {sessions_data}
        """

        self.username = None
        self.sessions_data = None

    def initialize_chat(self, username, sessions_data):
        """Initialize a new chat with username and session data"""
        self.username = username
        self.sessions_data = sessions_data

        # Create a new chat with updated system prompt
        system_prompt = self.system_prompt_template.format(
            username=self.username or "user",
            sessions_data=self.sessions_data
        )
        
        # Gemini doesn't have a dedicated system message, so we send it as a user message
        # and track it separately for our standardized format
        self.conversation_history = [{"role": "system", "content": system_prompt}]
        
        # Send the system prompt as a user message to Gemini
        self.send_message(system_prompt)
        return self.conversation_history

    def update_session_data(self, sessions_data):
        """Update the session data without adding to chat history"""
        if not self.chat:
            return None
            
        # Update stored session data
        self.sessions_data = sessions_data
        
        # Create a new chat with updated system prompt
        update_session_data_prompt = self.update_session_data_template.format(
            username=self.username or "user",
            sessions_data=self.sessions_data
        )

        response = self.chat.send_message(update_session_data_prompt)

        assistant_response = response.text

        # Add message to conversation history
        self.conversation_history.append({"role": "system", "content": update_session_data_prompt})
        self.conversation_history.append({"role": "assistant", "content": assistant_response})

        return assistant_response


    def send_message(self, message):
        """Send a message to the LLM and return the response"""
        try:
            # Add user message to our conversation history
            self.conversation_history.append({"role": "user", "content": message})

            # Send message to Gemini
            response = self.chat.send_message(message)

            # Extract response text
            assistant_response = response.text

            # Add assistant response to our conversation history
            self.conversation_history.append({"role": "assistant", "content": assistant_response})

            return assistant_response
        except Exception as e:
            error_msg = f"Error communicating with Gemini: {str(e)}"
            self.conversation_history.append({"role": "assistant", "content": error_msg})
            return error_msg

    def get_conversation_history(self):
        """Return standardized conversation history"""
        return self.conversation_history


# Factory function to get the appropriate handler
def get_llm_handler(provider="gemini"):
    if provider.lower() == "gemini":
        return GeminiHandler()
    # Add more handlers here as needed
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
