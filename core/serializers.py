from rest_framework import serializers
from core.models import *
from core.totals import annotate_project_totals, annotate_subproject_totals


def _derived_values(instance):
    total = getattr(instance, "derived_total_time", None)
    latest = getattr(instance, "derived_last_updated", None)
    if total is not None and latest is not None:
        return total, latest

    if isinstance(instance, Projects):
        queryset = annotate_project_totals(Projects.objects.filter(pk=instance.pk))
    else:
        queryset = annotate_subproject_totals(
            SubProjects.objects.filter(pk=instance.pk)
        )
    row = queryset.values("derived_total_time", "derived_last_updated").get()
    return row["derived_total_time"], row["derived_last_updated"]


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
            # start_date remains stored, mutable legacy metadata.
            'start_date',
            'last_updated'
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        total, latest = _derived_values(instance)
        representation["total_time"] = float(total)
        representation["last_updated"] = serializers.DateTimeField().to_representation(
            latest
        )
        return representation


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
            # start_date remains stored, mutable legacy metadata.
            'start_date',
            'last_updated',
            'subprojects'
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        total, latest = _derived_values(instance)
        representation["total_time"] = float(total)
        representation["last_updated"] = serializers.DateTimeField().to_representation(
            latest
        )
        return representation


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
            'auto_stop_at',
            'note',
            'is_active',
            'crosses_dst_transition',
        )
    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['project'] = instance.project.name
        rep['subprojects'] = [sp.name for sp in instance.subprojects.all()]
        return rep
