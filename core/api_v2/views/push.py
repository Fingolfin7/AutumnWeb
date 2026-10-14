from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from core.models import PushSubscription
from core.services.push import (
    PushValidationError,
    disable_subscription,
    enqueue_push_test,
    save_subscription,
    validate_endpoint,
    vapid_configuration,
)


class PushStatusSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    public_key = serializers.CharField(allow_blank=True, allow_null=True)
    configuration_error = serializers.CharField(allow_blank=True, allow_null=True)
    subscriptions = serializers.IntegerField()
    subscribed = serializers.BooleanField()


class PushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField()
    auth = serializers.CharField()


class PushSubscriptionRequestSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=2048)
    expirationTime = serializers.IntegerField(required=False, allow_null=True)
    keys = PushKeysSerializer()


class PushSubscriptionResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    active = serializers.BooleanField()


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=2048)


class PushRemovedSerializer(serializers.Serializer):
    removed = serializers.BooleanField()


class PushTestResponseSerializer(serializers.Serializer):
    queued = serializers.BooleanField()
    event_id = serializers.IntegerField()


class PushStatusView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="push_status_retrieve", responses=PushStatusSerializer)
    def get(self, request):
        active = PushSubscription.objects.filter(user=request.user, active=True).count()
        configuration = vapid_configuration()
        return Response(
            {
                "available": configuration["configured"],
                "public_key": configuration["public_key"],
                "configuration_error": configuration["error"],
                "subscriptions": active,
                "subscribed": active > 0,
            }
        )


class PushSubscriptionsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="push_subscriptions_create",
        request=PushSubscriptionRequestSerializer,
        responses={201: PushSubscriptionResponseSerializer},
    )
    def post(self, request):
        serializer = PushSubscriptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subscription = save_subscription(
                user=request.user, payload=serializer.validated_data
            )
        except PushValidationError as exc:
            raise ValidationError({"subscription": [str(exc)]}) from exc
        return Response(
            {"id": subscription.pk, "active": subscription.active},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="push_subscriptions_destroy",
        request=PushUnsubscribeSerializer,
        responses=PushRemovedSerializer,
    )
    def delete(self, request):
        serializer = PushUnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            endpoint = validate_endpoint(serializer.validated_data["endpoint"])
            subscription = disable_subscription(user=request.user, endpoint=endpoint)
        except PushValidationError as exc:
            raise ValidationError({"endpoint": [str(exc)]}) from exc
        return Response({"removed": subscription is not None})


class PushTestView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="push_test_create",
        request=None,
        responses={202: PushTestResponseSerializer},
    )
    def post(self, request):
        if request.data:
            raise ValidationError(
                {"non_field_errors": ["Push test accepts an empty JSON object only."]}
            )
        event = enqueue_push_test(user=request.user)
        return Response(
            {"queued": True, "event_id": event.pk},
            status=status.HTTP_202_ACCEPTED,
        )
