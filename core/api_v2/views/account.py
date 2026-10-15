from django import forms
from django.urls import reverse
from allauth.socialaccount.forms import DisconnectForm
from allauth.socialaccount.models import SocialAccount, SocialApp
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api_v2.exceptions import V2APIView
from users.codex_auth import (
    CodexAuthError,
    CodexDevicePending,
    poll_device_code_login,
    serialize_token_bundle,
    start_device_code_login,
    token_bundle_summary,
    deserialize_token_bundle,
)
from users.context_processors import configured_social_providers
from users.forms import ProfileUpdateForm, UserUpdateForm
from users.views import download_background


class AccountUpdateForm(UserUpdateForm):
    class Meta(UserUpdateForm.Meta):
        fields = ["username", "email", "first_name", "last_name"]


class AccountSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)


class AccountPatchSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one account field.")
        return attrs


class MediaStatusSerializer(serializers.Serializer):
    url = serializers.CharField(allow_null=True)


class ImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()


class ApiKeyRequestSerializer(serializers.Serializer):
    key = serializers.CharField(trim_whitespace=True, allow_blank=False)


class ConfiguredSerializer(serializers.Serializer):
    configured = serializers.BooleanField()


class ChatGPTLoginSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("pending", "connected", "disconnected"))
    user_code = serializers.CharField(required=False)
    verification_url = serializers.URLField(required=False)
    interval = serializers.IntegerField(required=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_null=True)
    plan = serializers.CharField(required=False, allow_null=True)
    account_id = serializers.CharField(required=False, allow_null=True)


class SocialAccountSerializer(serializers.Serializer):
    provider = serializers.CharField()
    name = serializers.CharField()
    connected = serializers.BooleanField()
    available = serializers.BooleanField()
    identity = serializers.CharField(allow_blank=True)
    login_url = serializers.CharField(allow_null=True)


class SocialAccountsSerializer(serializers.Serializer):
    accounts = SocialAccountSerializer(many=True)
    has_usable_password = serializers.BooleanField()


def _form_errors(form):
    return {
        field: [str(message) for message in messages]
        for field, messages in form.errors.items()
    }


def _pending_login_payload(device_code):
    """Return only browser-useful device data; keep the poll credential in session."""
    return {
        "status": "pending",
        "verification_url": device_code["verification_url"],
        "user_code": device_code["user_code"],
        "interval": device_code["interval"],
        "expires_at": device_code["expires_at"],
    }


class AccountView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="me_account_retrieve", responses=AccountSerializer)
    def get(self, request):
        return Response(AccountSerializer(request.user).data)

    @extend_schema(
        operation_id="me_account_partial_update",
        request=AccountPatchSerializer,
        responses=AccountSerializer,
    )
    def patch(self, request):
        serializer = AccountPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        merged = {
            field: serializer.validated_data.get(field, getattr(request.user, field))
            for field in ("username", "email", "first_name", "last_name")
        }
        form = AccountUpdateForm(merged, instance=request.user)
        if not form.is_valid():
            raise ValidationError(_form_errors(form))
        user = form.save()
        return Response(AccountSerializer(user).data)


class AvatarView(V2APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="me_avatar_update",
        request=ImageUploadSerializer,
        responses=MediaStatusSerializer,
    )
    def put(self, request):
        image = request.FILES.get("image")
        if image is None:
            raise ValidationError({"image": ["This field is required."]})
        try:
            image = ProfileUpdateForm.base_fields["image"].clean(image)
        except forms.ValidationError as exc:
            raise ValidationError({"image": list(exc.messages)}) from exc
        profile = request.user.profile
        profile.image = image
        profile.save(update_fields=["image"])
        return Response({"url": profile.image_url})

    @extend_schema(
        operation_id="me_avatar_destroy",
        request=None,
        responses={200: MediaStatusSerializer},
    )
    def delete(self, request):
        profile = request.user.profile
        profile.image = "default.jpg"
        profile.save(update_fields=["image"])
        return Response({"url": profile.image_url})


class BackgroundView(V2APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="me_background_update",
        request=ImageUploadSerializer,
        responses=MediaStatusSerializer,
    )
    def put(self, request):
        image = request.FILES.get("image")
        if image is None:
            raise ValidationError({"image": ["This field is required."]})
        try:
            image = ProfileUpdateForm.base_fields["background_image"].clean(image)
        except forms.ValidationError as exc:
            raise ValidationError({"image": list(exc.messages)}) from exc
        profile = request.user.profile
        profile.background_image = image
        profile.automatic_background = False
        profile.bing_background = False
        profile.nasa_apod_background = False
        profile.save(
            update_fields=[
                "background_image",
                "automatic_background",
                "bing_background",
                "nasa_apod_background",
            ]
        )
        return Response({"url": profile.background_image.url})

    @extend_schema(
        operation_id="me_background_destroy",
        request=None,
        responses={200: MediaStatusSerializer},
    )
    def delete(self, request):
        profile = request.user.profile
        profile.background_image = None
        profile.save(update_fields=["background_image"])
        return Response({"url": None})


class BackgroundDownloadView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="me_background_download_retrieve",
        responses={
            (200, "application/octet-stream"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Current automatic or uploaded background file download.",
            )
        },
    )
    def get(self, request):
        return download_background(request._request)


class ApiKeyView(V2APIView):
    permission_classes = [IsAuthenticated]
    PROVIDERS = {"gemini", "openai", "claude"}

    def _provider(self, provider):
        if provider not in self.PROVIDERS:
            raise NotFound("Unknown API key provider.")
        return provider

    @extend_schema(
        operation_id="me_api_keys_update",
        request=ApiKeyRequestSerializer,
        responses=ConfiguredSerializer,
    )
    def put(self, request, provider):
        provider = self._provider(provider)
        if not request.user.profile.ai_features_enabled:
            raise PermissionDenied("AI features are disabled for this account.")
        serializer = ApiKeyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = request.user.profile
        profile.set_api_key(provider, serializer.validated_data["key"])
        profile.save()
        return Response({"configured": True})

    @extend_schema(
        operation_id="me_api_keys_destroy",
        request=None,
        responses={200: ConfiguredSerializer},
    )
    def delete(self, request, provider):
        provider = self._provider(provider)
        if not request.user.profile.ai_features_enabled:
            raise PermissionDenied("AI features are disabled for this account.")
        profile = request.user.profile
        profile.set_api_key(provider, None)
        profile.save()
        return Response({"configured": False})


class ChatGPTLoginView(V2APIView):
    permission_classes = [IsAuthenticated]
    SESSION_KEY = "openai_chatgpt_device_code"

    def _allowed(self, request):
        if not request.user.profile.ai_features_enabled:
            raise PermissionDenied("AI features are disabled for this account.")

    @extend_schema(
        operation_id="me_chatgpt_login_create",
        request=None,
        responses={201: ChatGPTLoginSerializer},
    )
    def post(self, request):
        self._allowed(request)
        try:
            code = start_device_code_login()
        except CodexAuthError as exc:
            raise ValidationError({"login": [str(exc)]}) from exc
        session_data = code.as_session_dict()
        request.session[self.SESSION_KEY] = session_data
        return Response(
            _pending_login_payload(session_data),
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="me_chatgpt_login_retrieve",
        responses={200: ChatGPTLoginSerializer, 202: ChatGPTLoginSerializer},
    )
    def get(self, request):
        self._allowed(request)
        device_code = request.session.get(self.SESSION_KEY)
        if not device_code:
            bundle = deserialize_token_bundle(
                request.user.profile.get_api_key("openai_chatgpt")
            )
            if bundle:
                return Response({"status": "connected", **token_bundle_summary(bundle)})
            return Response({"status": "disconnected"})
        try:
            bundle = poll_device_code_login(device_code)
        except CodexDevicePending:
            return Response(
                _pending_login_payload(device_code),
                status=status.HTTP_202_ACCEPTED,
            )
        except CodexAuthError as exc:
            raise ValidationError({"login": [str(exc)]}) from exc
        profile = request.user.profile
        profile.set_api_key("openai_chatgpt", serialize_token_bundle(bundle))
        profile.save()
        request.session.pop(self.SESSION_KEY, None)
        return Response({"status": "connected", **token_bundle_summary(bundle)})

    @extend_schema(
        operation_id="me_chatgpt_login_destroy",
        request=None,
        responses={200: ChatGPTLoginSerializer},
    )
    def delete(self, request):
        profile = request.user.profile
        profile.set_api_key("openai_chatgpt", None)
        profile.save()
        request.session.pop(self.SESSION_KEY, None)
        return Response({"status": "disconnected"})


class SocialAccountsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="me_social_accounts_retrieve", responses=SocialAccountsSerializer)
    def get(self, request):
        connected = {
            account.provider: account
            for account in SocialAccount.objects.filter(
                user=request.user, provider__in=("google", "github")
            )
        }
        route_names = {"google": "google_login", "github": "github_login"}
        accounts = []
        for provider in configured_social_providers():
            account = connected.get(provider["id"])
            if not provider["enabled"] and account is None:
                continue
            identity = ""
            if account:
                identity = (
                    account.extra_data.get("email")
                    or account.extra_data.get("login")
                    or account.uid
                )
            accounts.append(
                {
                    "provider": provider["id"],
                    "name": provider["name"],
                    "connected": account is not None,
                    "available": provider["enabled"],
                    "identity": identity,
                    "login_url": (
                        request.build_absolute_uri(reverse(route_names[provider["id"]]))
                        if provider["enabled"] and account is None
                        else None
                    ),
                }
            )
        return Response(
            {
                "accounts": accounts,
                "has_usable_password": request.user.has_usable_password(),
            }
        )


class SocialAccountDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="me_social_accounts_destroy",
        request=None,
        responses={204: OpenApiResponse(description="Social account disconnected.")},
    )
    def delete(self, request, provider):
        if provider not in {"google", "github"}:
            raise NotFound("Unsupported social account provider.")
        account = SocialAccount.objects.filter(
            user=request.user, provider=provider
        ).first()
        if account is None:
            raise NotFound("Social account not found.")
        form = DisconnectForm(data={"account": account.pk}, request=request._request)
        if not form.is_valid():
            raise ValidationError(_form_errors(form))
        try:
            form.save()
        except SocialApp.DoesNotExist:
            # A connection can outlive deployment credentials for its provider.
            # The form has already enforced the last-login-method rule, so keep
            # that stale-but-visible connection removable from the profile.
            account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
