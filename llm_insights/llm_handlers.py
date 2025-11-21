from .gemini_handler import GeminiHandler
from .openai_handler import OpenAIHandler
from .claude_handler import ClaudeHandler

# Factory function to get the appropriate handler
def get_llm_handler(model="", api_keys: dict | None = None):
    api_keys = api_keys or {}
    low = model.lower()
    if "gemini" in low:
        return GeminiHandler(model=model, api_key=api_keys.get('gemini'))
    if any(x in low for x in ["gpt", "o1", "openai"]):
        return OpenAIHandler(model=model, api_key=api_keys.get('openai'))
    if "claude" in low:
        return ClaudeHandler(model=model, api_key=api_keys.get('claude'))
    raise ValueError(f"Unsupported model provider: {model}")
