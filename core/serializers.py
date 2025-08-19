from rest_framework import serializers
from core.models import *


class SubProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubProjects
        fields = (
            'id',
            'user',
            'name',
            'description',
            'total_time',
            'parent_project',
            'start_date',
            'last_updated'
        )


class ProjectSerializer(serializers.ModelSerializer):
    subprojects = SubProjectSerializer(many=True, read_only=True)

    class Meta:
        model = Projects
        fields =(
            'id',
            'user',
            'name',
            'status',
            'description',
            'total_time',
            'start_date',
            'last_updated',
            'subprojects'
        )


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sessions
        fields = (
            'id',
            'user',
            'project',
            'project_id',
            'subprojects',
            'start_time',
            'end_time',
            'note',
            'is_active'
        )
    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['project'] = instance.project.name
        rep['subprojects'] = [sp.name for sp in instance.subprojects.all()]
        return rep
