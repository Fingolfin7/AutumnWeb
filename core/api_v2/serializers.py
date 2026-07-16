from rest_framework import serializers


class MeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    timezone = serializers.CharField()


class MeSerializer(serializers.Serializer):
    api_version = serializers.IntegerField()
    capabilities = serializers.ListField(child=serializers.CharField())
    user = MeUserSerializer()
