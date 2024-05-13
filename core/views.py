from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from datetime import datetime, timedelta
from core.models import *
from core.serializers import ProjectSerializer, SubProjectSerializer, SessionSerializer


def home(request):
    return render(request, 'core/home.html')
