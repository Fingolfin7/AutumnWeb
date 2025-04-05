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
    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data the LLM is working with"""
        pass


def prep_session_data(sessions):
    projects_data = {}

    for session in sessions:
        project_name = session.project.name

        # Initialize project entry if it doesn't exist
        if project_name not in projects_data:
            projects_data[project_name] = {
                "Total Time": 0,
                "Status": session.project.status if hasattr(session.project, 'status') else "",
                "Description": session.project.description if hasattr(session.project, 'description') else "",
                "Sub Projects": {},
                "Session History": []
            }

        # Add session duration to total
        projects_data[project_name]["Total Time"] += session.duration

        # Track subprojects
        subprojects = [sp.name for sp in session.subprojects.all()]
        for subproject in subprojects:
            if subproject not in projects_data[project_name]["Sub Projects"]:
                projects_data[project_name]["Sub Projects"][subproject] = 0
            projects_data[project_name]["Sub Projects"][subproject] += session.duration

        # Add session to history
        session_entry = {
            "Date": session.end_time.strftime('%m-%d-%Y'),
            "Start Time": session.start_time.strftime('%H:%M:%S'),
            "End Time": session.end_time.strftime('%H:%M:%S'),
            "Sub-Projects": subprojects,
            "Duration": session.duration,
            "Note": session.note or ""
        }
        projects_data[project_name]["Session History"].append(session_entry)

    return json.dumps(projects_data, indent=2)


class GeminiHandler(BaseLLMHandler):
    """Handler for Google's Gemini API"""

    def __init__(self, model="gemini-2.0-flash"):
        self.api_key = settings.GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key)
        self.chat = self.client.chats.create(model=model)

        self.username = None
        self.session_data = None

        self.conversation_history = []

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
        """Initialize a new chat with username and session data"""
        self.username = username
        self.session_data = prep_session_data(sessions_data)

    def update_session_data(self, sessions_data, user_prompt):
        """Update the session data without adding to chat history"""
        if not self.chat:
            return None
            
        # Update stored session data
        self.session_data = prep_session_data(sessions_data)
        
        # Create a new chat with updated system prompt
        update_session_data_prompt = self.update_session_data_template.format(
            username=self.username,
            user_prompt=user_prompt,
            session_data=self.session_data
        )

        response = self.chat.send_message(update_session_data_prompt)

        assistant_response = response.text

        # Add message to conversation history
        self.conversation_history.append({"role": "system", "content": update_session_data_prompt})
        self.conversation_history.append({"role": "assistant", "content": assistant_response})

        return assistant_response

    def send_message(self, message):
        """Send a message to the LLM and return the response"""
        if len(self.conversation_history) == 0:
            # send system prompt along with user message
            initial_prompt = self.system_prompt_template.format(
                username=self.username,
                user_prompt=message,
                session_data=self.session_data
            )
            response = self.chat.send_message(initial_prompt)
            self.conversation_history.append({"role": "system", "content": initial_prompt})
            self.conversation_history.append({"role": "user", "content": message}) # for display purposes, only show what the user sent
        else:
            self.conversation_history.append({"role": "user", "content": message})
            response = self.chat.send_message(message)

        # Extract response text
        assistant_response = response.text

        # Add assistant response to our conversation history
        self.conversation_history.append({"role": "assistant", "content": assistant_response})

        return assistant_response
        # try:
        #     if len(self.conversation_history) == 0:
        #         # send system prompt along with user message
        #         initial_prompt = self.system_prompt_template(
        #             username = self.username,
        #             user_prompt = message,
        #             session_data = self.session_data
        #         )
        #     # Add user message to our conversation history
        #     self.conversation_history.append({"role": "user", "content": message})
        #
        #     # Send message to Gemini
        #     response = self.chat.send_message(message)
        #
        #     # Extract response text
        #     assistant_response = response.text
        #
        #     # Add assistant response to our conversation history
        #     self.conversation_history.append({"role": "assistant", "content": assistant_response})
        #
        #     return assistant_response
        # except Exception as e:
        #     error_msg = f"Error communicating with Gemini: {str(e)}"
        #     self.conversation_history.append({"role": "assistant", "content": error_msg})
        #     return error_msg

    def get_conversation_history(self):
        """Return standardized conversation history"""
        return self.conversation_history


# Factory function to get the appropriate handler
def get_llm_handler(model=""):
    gemini_models = ["gemini-2.0-flash", "gemini-2.0",
                     "gemini-2.0-flash-lite", "gemini-2.5-pro-exp-03-25",
                     "gemini-2.0-flash-thinking-exp-01-21"]
    if model.lower() in gemini_models:
        return GeminiHandler(model=model)
    # Add more handlers here as needed
    else:
        raise ValueError(f"Unsupported model provider: {model}")
