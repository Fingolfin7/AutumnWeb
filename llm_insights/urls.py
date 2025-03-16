from llm_insights.views import *
from django.urls import path

urlpatterns = [
    path('', insights_view, name='insights'),
]