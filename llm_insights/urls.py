from django.urls import path

from llm_insights.views import InsightsView, delete_chat, stream_insights

urlpatterns = [
    path("", InsightsView.as_view(), name="insights"),
    path("stream/", stream_insights, name="insights_stream"),
    path("<uuid:chat_id>/", InsightsView.as_view(), name="insights_detail"),
    path(
        "<uuid:chat_id>/stream/",
        stream_insights,
        name="insights_detail_stream",
    ),
    path("delete/<uuid:chat_id>/", delete_chat, name="delete_chat"),
]
