from django.db import models
from django.contrib.auth.models import User
import uuid


class LLMChat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="llm_chats")
    title = models.CharField(max_length=255, default="New Chat")
    model = models.CharField(max_length=100)
    filters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.title} ({self.user.username})"


class LLMMessage(models.Model):
    chat = models.ForeignKey(LLMChat, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)  # system, user, assistant
    content = models.TextField()
    metadata = models.JSONField(
        default=dict, blank=True
    )  # For sources, token usage, etc.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


def attachment_upload_to(instance, filename):
    return f"insights/attachments/{instance.user_id}/{instance.id}/{filename}"


class LLMAttachment(models.Model):
    """A file added to an Insights question: a screenshot, a PDF, or a text
    document whose text was extracted once at upload (``text``) so every
    provider can read it on every later turn. Unsent uploads have no message;
    the file in storage is removed with the row (llm_insights.attachments)."""

    KIND_IMAGE = "image"
    KIND_PDF = "pdf"
    KIND_TEXT = "text"
    KIND_CHOICES = [(KIND_IMAGE, "Image"), (KIND_PDF, "PDF"), (KIND_TEXT, "Text")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="llm_attachments"
    )
    message = models.ForeignKey(
        LLMMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to=attachment_upload_to, max_length=300)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    mime = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"
