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
