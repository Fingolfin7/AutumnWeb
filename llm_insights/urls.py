from llm_insights.views import *
from django.urls import path

urlpatterns = [
    path("", InsightsView.as_view(), name="insights"),
    path("<uuid:chat_id>/", InsightsView.as_view(), name="insights_detail"),
    path("delete/<uuid:chat_id>/", delete_chat, name="delete_chat"),
]
