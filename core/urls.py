from django.urls import path
from core.views import *

urlpatterns = [
    path('', home, name='home'),
    path('projects/', ProjectsListView.as_view(), name='projects'),
    path('timers/', TimerListView.as_view(), name='timers'),
    path('start_timer/', start_timer, name='start_timer'),
    path('stop_timer/<int:session_id>/', stop_timer, name='stop_timer'),
    path('restart_timer/<int:session_id>/', restart_timer, name='restart_timer'),
    path('remove_timer/<int:session_id>/', remove_timer, name='remove_timer'),
    path('create_subproject/', CreateProjectView.as_view(), name='create_project'),
    path('create_subproject/<str:project_name>/', CreateSubProjectView.as_view(), name='create_subproject'),
    path('update_project/<str:project_name>/', UpdateProjectView.as_view(), name='update_project'),
    path('update_subproject/<int:pk>/', UpdateSubProjectView.as_view(), name='update_subproject'),
    path('delete_project/<str:project_name>/', DeleteProjectView.as_view(), name='delete_project'),
    path('delete_subproject/<int:pk>/', DeleteSubProjectView.as_view(), name='delete_subproject'),
    path('sessions/', SessionsListView.as_view(), name='sessions'),
    path('update_session/<int:session_id>/', update_session, name='update_session'),
    path('delete_session/<int:session_id>/', DeleteSessionView.as_view(), name='delete_session'),
    path('charts/', ChartsView, name='charts'),
    path('import/', import_view, name='import'),

    # api paths
    path('api/create_project/', create_project, name='api_create_project'),
    path('api/list_projects/', list_projects, name='api_list_projects'),

    path('api/tally_by_sessons/', tally_by_sessions, name='api_tally_by_sessions'),
    path('api/search_projects/', search_projects, name='api_search_projects'),
    path('api/get_project/<str:project_name>/', get_project, name='api_get_project'),
    path('api/delete_project/<str:project_name>/', delete_project, name='api_delete_project'),
    # path('api/create_subproject/', create_subproject, name='create_subproject'),
    path('api/list_subprojects/<str:project_name>/', list_subprojects, name='api_list_subprojects'),
    path('api/list_subprojects/', list_subprojects, name='api_list_subprojects_param'),
    path('api/search_subprojects/', search_subprojects, name='api_search_subprojects'),
    path('api/delete_subproject/<str:project_name>/<str:subproject_name>/', delete_subproject,
         name='api_delete_subproject'),
    path('api/start_session/', start_session, name='api_start_session'),
    path('api/end_session/', end_session, name='api_end_session'),
    path('api/log_session/', log_session, name='api_log_session'),
    path('api/delete_session/<int:session_id>/', delete_session, name='api_delete_session'),
    path('api/list_sessions/', list_sessions, name='api_list_sessions'),
    path('api/list_active_sessions/', list_active_sessions, name='api_list_active_sessions'),
]