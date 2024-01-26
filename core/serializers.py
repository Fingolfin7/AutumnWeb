from rest_framework import serializers
from core.models import *


class SubProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubProjects
        fields = '__all__'


class ProjectSerializer(serializers.ModelSerializer):
    subprojects = SubProjectSerializer(many=True, read_only=True)

    class Meta:
        model = Projects
        fields = '__all__'


class SessionSerializer(serializers.ModelSerializer):
    project = ProjectSerializer(read_only=True)
    subprojects = SubProjectSerializer(many=True, read_only=True)

    class Meta:
        model = Sessions
        fields = '__all__'
