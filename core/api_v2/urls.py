from django.urls import path

from core.api_v2.views import MeView


app_name = "api_v2"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
]
