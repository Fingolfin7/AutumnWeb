from django.urls import path
from core.views import *

urlpatterns = [
    path('', home, name='home'),
    path('projects/', ProjectsListView.as_view(), name='projects'),
    path('timers/', TimerListView.as_view(), name='timers'),
    path('start_timer/', start_timer, name='start_timer'),
    path('stop_timer/<int:session_id>', stop_timer, name='stop_timer'),
    path('restart_timer/<int:session_id>', restart_timer, name='restart_timer'),
    path('remove_timer/<int:session_id>', remove_timer, name='remove_timer'),
    path('projects/create/', CreateProjectView.as_view(), name='create_project'),
    path('projects/<int:pk>/create_subproject/', CreateSubProjectView.as_view(), name='create_subproject'),

    # api paths
    # path('api/create_project/', create_project, name='create_project'),
    path('api/list_projects/', list_projects, name='list_projects'),
    path('api/search_projects/', search_projects, name='search_projects'),
    path('api/get_project/<str:project_name>/', get_project, name='get_project'),
    path('api/delete_project/<str:project_name>/', delete_project, name='delete_project'),
    # path('api/create_subproject/', create_subproject, name='create_subproject'),
    path('api/list_subprojects/<str:project_name>/', list_subprojects, name='list_subprojects'),
    path('api/list_subprojects/', list_subprojects, name='list_subprojects_param'),
    path('api/search_subprojects/', search_subprojects, name='search_subprojects'),
    path('api/delete_subproject/<str:project_name>/<str:subproject_name>/', delete_subproject, name='delete_subproject'),
    path('api/start_session/', start_session, name='start_session'),
    path('api/end_session/', end_session, name='end_session'),
    path('api/log_session/', log_session, name='log_session'),
    path('api/delete_session/<int:session_id>/', delete_session, name='delete_session'),
    path('api/list_sessions/', list_sessions, name='list_sessions'),
    path('api/list_active_sessions/', list_active_sessions, name='list_active_sessions'),
]