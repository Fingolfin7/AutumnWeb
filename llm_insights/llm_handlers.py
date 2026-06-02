from .gemini_handler import GeminiHandler
from .openai_handler import OpenAIHandler
from .openai_chatgpt_handler import OpenAIChatGPTHandler
from .claude_handler import ClaudeHandler

# Factory function to get the appropriate handler
def get_llm_handler(
    model="", api_keys: dict | None = None, reasoning_effort: str | None = None
):
    api_keys = api_keys or {}
    model_name_lower = model.lower()
    if "gemini" in model_name_lower:
        return GeminiHandler(model=model, api_key=api_keys.get("gemini"))
    if "codex" in model_name_lower:
        return OpenAIChatGPTHandler(
            model=model,
            bearer_token=api_keys.get("openai_chatgpt"),
            reasoning_effort=reasoning_effort,
        )
    if any(
        x in model_name_lower for x in ["gpt", "openai"]
    ) or model_name_lower.startswith("o"):
        if api_keys.get("openai_chatgpt") and not api_keys.get("openai"):
            return OpenAIChatGPTHandler(
                model=model,
                bearer_token=api_keys.get("openai_chatgpt"),
                reasoning_effort=reasoning_effort,
            )
        return OpenAIHandler(
            model=model,
            api_key=api_keys.get("openai"),
            reasoning_effort=reasoning_effort,
        )
    if any(x in model_name_lower for x in ["claude", "sonnet", "haiku", "opus"]):
        return ClaudeHandler(model=model, api_key=api_keys.get("claude"))
    raise ValueError(f"Unsupported model provider: {model}")
