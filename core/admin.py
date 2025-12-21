from django.contrib import admin
from .models import *

admin.site.register(Projects)
admin.site.register(SubProjects)
admin.site.register(Sessions)
admin.site.register(Context)
admin.site.register(Tag)

