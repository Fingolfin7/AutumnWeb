from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from llm_insights.models import LLMAttachment, LLMChat, LLMMessage
from llm_insights.session_context import SESSION_FILTERS_KEY


@transaction.atomic
def branch_chat(user, chat_id, message_id):
    source = get_object_or_404(LLMChat.objects.select_for_update(), user=user, pk=chat_id)
    anchor = get_object_or_404(source.messages, pk=message_id, role__in=("user", "assistant"))
    prefix = list(source.messages.filter(
        Q(created_at__lt=anchor.created_at) | Q(created_at=anchor.created_at, pk__lte=anchor.pk)
    ))
    filters = source.filters or {}
    for message in reversed(prefix):
        if message.role == "system":
            # Old transcripts predate per-selection snapshots.
            filters = message.metadata.get(SESSION_FILTERS_KEY, filters)
            break
    branch = LLMChat.objects.create(
        user=user, branched_from=source, title=f"Branch · {source.title}"[:255],
        model=source.model, filters={**filters, "reasoning_effort": (source.filters or {}).get("reasoning_effort", "")},
    )
    copies = LLMMessage.objects.bulk_create([
        LLMMessage(chat=branch, role=m.role, content=m.content, metadata=m.metadata) for m in prefix
    ])
    by_original = dict(zip((m.pk for m in prefix), copies))
    for original, copy in zip(prefix, copies):
        copy.created_at = original.created_at
    LLMMessage.objects.bulk_update(copies, ["created_at"])

    # The copies share the stored files, so a branch takes no extra space.
    files = LLMAttachment.objects.select_for_update().filter(message_id__in=by_original, user=user)
    LLMAttachment.objects.bulk_create([
        LLMAttachment(user=user, message=by_original[f.message_id], file=f.file.name,
                      name=f.name, kind=f.kind, mime=f.mime, size=f.size, text=f.text)
        for f in files
    ])
    return branch
