from django.urls import path
from core.views import start, stop, status, create_project, get_projects, get_session_logs

urlpatterns = [
    # path('start_timer', views.start_timer, name='start_timer'),
    path('', get_projects),
    path('start/', start),
    path('stop/', stop),
    path('status/', status),
    path('create_project/', create_project),
    path('get_projects/', get_projects),
    path('get_session_logs/', get_session_logs),
]