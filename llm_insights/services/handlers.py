import os

from llm_insights.llm_handlers import get_llm_handler
from users.codex_auth import get_profile_access_token


OPENAI_REASONING_EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def provider_models(user):
    profile = getattr(user, "profile", None)
    models = {}
    if (
        (profile and profile.openai_api_key_enc)
        or (profile and profile.openai_chatgpt_token_enc)
        or os.environ.get("OPENAI_API_KEY")
    ):
        models["openai"] = [
            ("gpt-6-luna", "GPT-6 Luna"),
            ("gpt-6-sol", "GPT-6 Sol"),
            ("gpt-6-astra", "GPT-6 Astra"),
            ("gpt-5.5", "GPT-5.5"),
        ]
    if profile and profile.gemini_api_key_enc:
        models["gemini"] = [
            ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
            ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
        ]
    if profile and profile.claude_api_key_enc:
        models["claude"] = [
            ("claude-haiku-4-5", "Claude Haiku 4.5"),
            ("claude-sonnet-5", "Claude Sonnet 5"),
            ("claude-opus-5", "Claude Opus 5"),
            ("claude-fable-5", "Claude Fable 5"),
        ]
    return models


def openai_connection_source(user):
    profile = getattr(user, "profile", None)
    if profile and profile.openai_chatgpt_token_enc and profile.openai_api_key_enc:
        return "codex_with_api_fallback"
    if profile and profile.openai_chatgpt_token_enc:
        return "codex"
    if profile and profile.openai_api_key_enc:
        return "profile"
    if os.environ.get("OPENAI_API_KEY"):
        return "server"
    return ""


def build_api_keys(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return {}
    return {
        "gemini": profile.get_api_key("gemini"),
        "openai": profile.get_api_key("openai"),
        "openai_chatgpt": get_profile_access_token(profile),
        "claude": profile.get_api_key("claude"),
    }


def validate_selection(models, provider, model):
    if provider == "openai":
        model = {
            "gpt-5.6-luna": "gpt-6-luna",
            "gpt-5.6-sol": "gpt-6-sol",
            "gpt-5.6": "gpt-6-sol",
            "gpt-5.6-terra": "gpt-6-sol",
        }.get(model, model)
    if not provider or provider not in models:
        provider = next(iter(models.keys()))
    valid_models = models[provider]
    model_values = [item[0] for item in valid_models]
    if not model or model not in model_values:
        model = model_values[0]
    return provider, model


def openai_reasoning_efforts(model):
    if model and not model.startswith(("gpt-5.6", "gpt-6-")):
        return OPENAI_REASONING_EFFORTS[:-1]
    return OPENAI_REASONING_EFFORTS


def validate_reasoning_effort(provider, effort, model=None):
    if provider != "openai":
        return ""
    if effort == "extra-high":
        effort = "xhigh"
    if effort not in openai_reasoning_efforts(model):
        return "high"
    return effort


def get_chat_title_handler(selected_handler, api_keys):
    """Prefer Luna for titles whenever the user has OpenAI auth configured."""
    if not (
        api_keys.get("openai")
        or api_keys.get("openai_chatgpt")
        or os.environ.get("OPENAI_API_KEY")
    ):
        return selected_handler
    return get_llm_handler(
        model="gpt-6-luna",
        api_keys=api_keys,
        reasoning_effort="high",
    )
