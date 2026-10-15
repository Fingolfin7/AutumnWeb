from django.urls import path

from core.spa import spa
from llm_insights.views import delete_chat, stream_insights

urlpatterns = [
    path("", spa, name="insights"),
    path("stream/", stream_insights, name="insights_stream"),
    path("<uuid:chat_id>/", spa, name="insights_detail"),
    path(
        "<uuid:chat_id>/stream/",
        stream_insights,
        name="insights_detail_stream",
    ),
    path("delete/<uuid:chat_id>/", delete_chat, name="delete_chat"),
]
