import json
from abc import ABC, abstractmethod
from google import genai
from AutumnWeb import settings


class BaseLLMHandler(ABC):
    """Abstract base class for LLM handlers"""

    @abstractmethod
    def initialize_chat(self, system_prompt):
        pass

    @abstractmethod
    def send_message(self, message):
        pass

    @abstractmethod
    def get_conversation_history(self):
        pass

    @abstractmethod
    def load_conversation(self, conversation_data):
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
        self.chat = None
        self.conversation_history = []
        self.system_prompt_template = """
        You are an expert project and time tracking analyst. Your job is to analyze projects, sessions,
        and session logs to provide insights based on the data provided.

        The user's name is {username} and this application is known as "Autumn".

        If possible please quote the session notes and dates/times for any insights you provide.

        Sessions data:
        {sessions_data}
        """
        self.username = None
        self.sessions_data = None

    def initialize_chat(self, system_prompt):
        """Initialize a new chat with system prompt"""
        self.chat = self.client.chats.create(model="gemini-2.0-flash")
        
        # Store the original session data and username for later updates
        if "The user's name is" in system_prompt:
            self.username = system_prompt.split("The user's name is ")[1].split(" ")[0]
        
        if "Sessions data:" in system_prompt:
            self.sessions_data = system_prompt.split("Sessions data:")[1].strip()
        
        # Gemini doesn't have a dedicated system message, so we send it as a user message
        # and track it separately for our standardized format
        self.conversation_history = [{"role": "system", "content": system_prompt}]
        
        # Send the system prompt as a user message to Gemini
        self.chat.send_message(system_prompt)
        return self.conversation_history

    def update_session_data(self, sessions_data):
        """Update the session data without adding to chat history"""
        if not self.chat:
            return None
            
        # Update stored session data
        self.sessions_data = sessions_data
        
        # Create a new chat with updated system prompt
        new_system_prompt = self.system_prompt_template.format(
            username=self.username or "user",
            sessions_data=self.sessions_data
        )
        
        # Create a new chat instance
        new_chat = self.client.chats.create(model="gemini-2.0-flash")
        
        # Send the new system prompt
        new_chat.send_message(new_system_prompt)
        
        # Replace old chat with new one
        self.chat = new_chat
        
        # Update system prompt in conversation history without adding a new message
        for i, msg in enumerate(self.conversation_history):
            if msg["role"] == "system":
                self.conversation_history[i]["content"] = new_system_prompt
                break
        
        # Send all user-assistant exchanges to rebuild conversation state
        user_messages = [msg for msg in self.conversation_history if msg["role"] in ["user", "assistant"]]
        for i in range(0, len(user_messages), 2):
            if i < len(user_messages):
                user_msg = user_messages[i]["content"]
                self.chat.send_message(user_msg)
        
        return self.conversation_history

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

    def load_conversation(self, conversation_data):
        """Load a conversation from saved data"""
        if not conversation_data:
            return None

        # Create a new chat
        self.chat = self.client.chats.create(model="gemini-2.0-flash")
        self.conversation_history = []

        # Extract system prompt to get username and session data
        for msg in conversation_data:
            if msg["role"] == "system":
                if "The user's name is" in msg["content"]:
                    self.username = msg["content"].split("The user's name is ")[1].split(" ")[0]
                
                if "Sessions data:" in msg["content"]:
                    self.sessions_data = msg["content"].split("Sessions data:")[1].strip()
                break

        # Process each message in the saved conversation
        for msg in conversation_data:
            if msg["role"] == "system":
                # Add system message to our history but send as user message to Gemini
                self.conversation_history.append(msg)
                self.chat.send_message(msg["content"])
            elif msg["role"] == "user":
                # Add user message to our history and send to Gemini
                self.conversation_history.append(msg)
                self.chat.send_message(msg["content"])
            elif msg["role"] == "assistant":
                # Just add to our history, as Gemini already has this in its state
                self.conversation_history.append(msg)

        return self.conversation_history


# Factory function to get the appropriate handler
def get_llm_handler(provider="gemini"):
    if provider.lower() == "gemini":
        return GeminiHandler()
    # Add more handlers here as needed
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
