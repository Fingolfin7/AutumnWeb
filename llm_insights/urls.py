from llm_insights.views import *
from django.urls import path

urlpatterns = [
    path('', InsightsView.as_view(), name='insights'),
]