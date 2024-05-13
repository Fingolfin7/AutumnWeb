from django.urls import path
from core.views import *

urlpatterns = [
    # path('start_timer', views.start_timer, name='start_timer'),
    path('', home),
]