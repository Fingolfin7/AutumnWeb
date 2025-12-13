from .gemini_handler import GeminiHandler
from .openai_handler import OpenAIHandler
from .claude_handler import ClaudeHandler

# Factory function to get the appropriate handler
def get_llm_handler(model="", api_keys: dict | None = None):
    api_keys = api_keys or {}
    model_name_lower = model.lower()
    if "gemini" in model_name_lower:
        return GeminiHandler(model=model, api_key=api_keys.get('gemini'))
    if any(x in model_name_lower for x in ["gpt", "openai"]) or model_name_lower.startswith("o"):
        return OpenAIHandler(model=model, api_key=api_keys.get('openai'))
    if any(x in model_name_lower for x in ["claude", "sonnet", "haiku", "opus"]):
        return ClaudeHandler(model=model, api_key=api_keys.get('claude'))
    raise ValueError(f"Unsupported model provider: {model}")
