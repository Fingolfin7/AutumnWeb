import re

from asgiref.sync import sync_to_async
from django.db import close_old_connections, transaction
from django.utils import timezone

from llm_insights.models import LLMChat, LLMMessage


def database_sync_to_async(func):
    def wrapped(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()

    return sync_to_async(wrapped)


def group_chats_by_recency(chats):
    """Bucket newest-first chats into the sidebar's recency groups."""
    today = timezone.localdate()
    buckets = [
        ("Today", []),
        ("Yesterday", []),
        ("Previous 7 days", []),
        ("Older", []),
    ]
    for chat in chats:
        if not chat.updated_at:
            buckets[3][1].append(chat)
            continue
        days_diff = (today - timezone.localtime(chat.updated_at).date()).days
        if days_diff <= 0:
            buckets[0][1].append(chat)
        elif days_diff == 1:
            buckets[1][1].append(chat)
        elif days_diff <= 7:
            buckets[2][1].append(chat)
        else:
            buckets[3][1].append(chat)
    return [(label, items) for label, items in buckets if items]


def fallback_chat_title(user_prompt):
    title = re.sub(r"\s+", " ", (user_prompt or "").strip())
    if not title:
        return "New Chat"
    return title[:40] + "..." if len(title) > 40 else title


def build_chat_title_prompt(conversation_history):
    visible_messages = [
        msg
        for msg in conversation_history
        if msg.get("role") in {"user", "assistant"} and msg.get("content")
    ]
    if not visible_messages:
        return ""

    transcript_parts = []
    for msg in visible_messages[-8:]:
        content = re.sub(r"\s+", " ", str(msg.get("content", ""))).strip()
        if len(content) > 1200:
            content = f"{content[:1200]}..."
        transcript_parts.append(f"{msg['role'].title()}: {content}")

    transcript = "\n".join(transcript_parts)
    return (
        "Write a concise, specific title for this Autumn AI insights chat. "
        "Use 3 to 8 words. Avoid generic labels like Session Analysis, Chat, or Summary. "
        "Return only the title, with no quotes, markdown, or trailing punctuation.\n\n"
        f"Chat transcript:\n{transcript}"
    )


def clean_generated_chat_title(raw_title, fallback_title):
    title = re.sub(r"^```(?:text)?|```$", "", (raw_title or "").strip()).strip()
    title = re.sub(r"^(title\s*:\s*)", "", title, flags=re.IGNORECASE).strip()
    title = title.strip("\"'` ")
    if not title:
        return fallback_title
    if "\n" in title:
        title = title.splitlines()[0].strip()
    title = re.sub(r"\s+", " ", title)
    title = title.rstrip(".:;,- ")
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title or fallback_title


async def generate_and_save_chat_title(
    chat_obj, llm_handler, conversation_history, fallback_title=None
):
    prompt = build_chat_title_prompt(conversation_history)
    if not prompt:
        return fallback_title or getattr(chat_obj, "title", "New Chat")

    fallback_title = fallback_title or getattr(chat_obj, "title", None) or "New Chat"
    try:
        raw_title = await llm_handler.generate_chat_title(prompt)
    except Exception:
        return fallback_title

    title = clean_generated_chat_title(raw_title, fallback_title)
    if title == fallback_title:
        return title

    chat_id = getattr(chat_obj, "id", chat_obj)

    def save_title():
        chat = LLMChat.objects.get(id=chat_id)
        chat.title = title
        chat.save(update_fields=["title", "updated_at"])

    await database_sync_to_async(save_title)()
    if hasattr(chat_obj, "title"):
        chat_obj.title = title
    return title


def serialize_message(message, *, include_metadata=False, include_auth_source=False):
    data = {
        "role": message.role,
        "content": message.content,
        "sources": message.metadata.get("sources", []),
        "model": message.metadata.get("model", ""),
    }
    if include_metadata:
        data["metadata"] = message.metadata
    else:
        data["usage"] = message.metadata.get("usage", {})
        data["refusal"] = message.metadata.get("refusal", False)
    if include_auth_source:
        data["auth_source"] = message.metadata.get("auth_source", "")
    return data


def load_chat_history(chat_obj, *, include_metadata=False, include_auth_source=False):
    return [
        serialize_message(
            message,
            include_metadata=include_metadata,
            include_auth_source=include_auth_source,
        )
        for message in chat_obj.messages.all()
    ]


async def save_llm_messages(chat_obj, messages_to_save):
    chat_id = getattr(chat_obj, "id", chat_obj)

    def create_messages():
        chat = LLMChat.objects.get(id=chat_id)
        with transaction.atomic():
            for msg in messages_to_save:
                LLMMessage.objects.create(
                    chat=chat,
                    role=msg["role"],
                    content=msg["content"],
                    metadata={
                        "sources": msg.get("sources", []),
                        "model": msg.get("model", ""),
                        "usage": msg.get("usage", {}),
                        "auth_source": msg.get("auth_source", ""),
                        "error": msg.get("error", False),
                        "error_message": msg.get("error_message", ""),
                        "refusal": msg.get("refusal", False),
                    },
                )

    await database_sync_to_async(create_messages)()


async def save_partial_stream_messages(
    chat_obj,
    previous_history,
    llm_handler,
    user_prompt,
    assistant_content,
    model,
    error_message,
):
    current_history = llm_handler.get_conversation_history() if llm_handler else []
    pending_messages = (
        current_history[len(previous_history):]
        if len(current_history) >= len(previous_history)
        else []
    )

    if pending_messages:
        has_assistant = any(msg.get("role") == "assistant" for msg in pending_messages)
        if not has_assistant:
            pending_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "model": model,
                    "usage": {"prompt": 0, "response": 0},
                    "error": True,
                    "error_message": error_message,
                }
            )
    elif user_prompt:
        pending_messages = [
            {"role": "user", "content": user_prompt},
            {
                "role": "assistant",
                "content": assistant_content,
                "model": model,
                "usage": {"prompt": 0, "response": 0},
                "error": True,
                "error_message": error_message,
            },
        ]

    if pending_messages:
        await save_llm_messages(chat_obj, pending_messages)
