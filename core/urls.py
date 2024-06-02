from django.urls import path
from core.views import *

urlpatterns = [
    # path('start_timer', views.start_timer, name='start_timer'),
    path('', home),
    path('api/create_project/', create_project, name='create_project'),
    path('api/list_projects/', list_projects, name='list_projects'),
    path('api/get_project/<str:project_name>/', get_project, name='get_project'),
    path('api/delete_project/<str:project_name>/', delete_project, name='delete_project'),
    path('api/create_subproject/', create_subproject, name='create_subproject'),
    path('api/list_subprojects/<str:project_name>/', list_subprojects, name='list_subprojects'),
    path('api/delete_subproject/<str:project_name>/<str:subproject_name>/', delete_subproject, name='delete_subproject'),
    path('api/start_session/', start_session, name='start_session'),
    path('api/end_session/', end_session, name='end_session'),
    path('api/log_session/', log_session, name='log_session'),
    path('api/delete_session/<int:session_id>/', delete_session, name='delete_session'),
    path('api/list_sessions/', list_sessions, name='list_sessions'),
    path('api/list_active_sessions/', list_active_sessions, name='list_active_sessions'),
]