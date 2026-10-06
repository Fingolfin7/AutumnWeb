"""Self-service OAuth consent and account linking for the single Autumn MCP."""
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, quote, urlsplit

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.csrf import csrf_exempt
from oauth2_provider.forms import AllowForm
from oauth2_provider.cimd import CIMDError, SafeMetadataFetcher
from oauth2_provider.models import AccessToken, Application, Grant, RefreshToken
from oauth2_provider.views import AuthorizationView, DynamicClientRegistrationView, DynamicClientRegistrationManagementView, RevokeTokenView, TokenView

from core.models import MCPAccountLink, MCPGrant, MCPGrantAccount
from users.forms import UserLoginForm


class MCPMetadataFetcher(SafeMetadataFetcher):
    """Keep hardened fetching; select the code flow from multi-flow client metadata."""
    def fetch(self, client_id):
        metadata, max_age = super().fetch(client_id)
        grants = metadata.get("grant_types", ["authorization_code"])
        if not isinstance(grants, list) or not all(isinstance(grant, str) for grant in grants) or "authorization_code" not in grants:
            raise CIMDError("This MCP requires authorization_code client support")
        # Claude also advertises jwt-bearer. It is not a grant this server accepts.
        metadata = {**metadata, "grant_types": [grant for grant in grants if grant in {"authorization_code", "refresh_token"}]}
        return metadata, max_age


def available_accounts(user):
    return User.objects.filter(Q(pk=user.pk) | Q(mcp_linked_by__owner=user), is_active=True).distinct().order_by("username")


def account_names(accounts):
    folded = [user.username.casefold() for user in accounts]
    return {user.pk: user.username if len(user.username) <= 128 and folded.count(user.username.casefold()) == 1
            else f"{user.username[:110]} ({user.pk})" for user in accounts}


def revoke_tokens(owner, application):
    # Also remove unredeemed codes so an earlier consent cannot inherit new accounts.
    RefreshToken.objects.filter(user=owner, application=application).delete()
    AccessToken.objects.filter(user=owner, application=application).delete()
    Grant.objects.filter(user=owner, application=application).delete()


def _limited(request, purpose, limit):
    identity = f"{request.META.get('REMOTE_ADDR', '')}:{getattr(request.user, 'pk', '')}"
    key = "mcp:" + purpose + ":" + hashlib.sha256(identity.encode()).hexdigest()
    if cache.add(key, 1, timeout=900):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        cache.set(key, 1, timeout=900)
        return False


class MCPConsentForm(AllowForm):
    accounts = forms.ModelMultipleChoiceField(queryset=User.objects.none(), required=False,
                                              widget=forms.CheckboxSelectMultiple, label="Accounts to share")
    default_account = forms.ModelChoiceField(queryset=User.objects.none(), required=False, label="Default account")
    allow_writes = forms.BooleanField(required=False, label="Allow changes to records in these accounts")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = available_accounts(user)
        self.fields["accounts"].queryset = accounts
        self.fields["default_account"].queryset = accounts
        self.fields["accounts"].initial = [user.pk]
        self.fields["default_account"].initial = user.pk
        self.fields["accounts"].label_from_instance = lambda account: account.username
        self.fields["default_account"].label_from_instance = lambda account: account.username

    def clean(self):
        data = super().clean()
        if not data.get("allow"):
            return data
        accounts = list(data.get("accounts") or [])
        default = data.get("default_account")
        if not accounts:
            self.add_error("accounts", "Choose at least one account.")
        if default is None or default not in accounts:
            self.add_error("default_account", "Choose a default from the accounts you selected.")
        requested = set(data.get("scope", "").split())
        if "autumn:read" not in requested or requested - {"autumn:read", "autumn:write"}:
            raise forms.ValidationError("This client requested unsupported permissions.")
        data["scope"] = "autumn:read" + (" autumn:write" if data.get("allow_writes") and "autumn:write" in requested else "")
        if data.get("resource", "").split() != [settings.MCP_RESOURCE]:
            raise forms.ValidationError("This connection must target Autumn MCP.")
        return data


class MCPAuthorizationView(AuthorizationView):
    template_name = "core/mcp_authorize.html"
    form_class = MCPConsentForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_initial(self):
        initial = super().get_initial()
        initial["resource"] = initial.get("resource") or settings.MCP_RESOURCE
        return initial

    def get(self, request, *args, **kwargs):
        # Account consent must always be displayed, including repeat connections.
        if Application.objects.filter(client_id=request.GET.get("client_id", ""), skip_authorization=True).exists():
            return HttpResponse("Account consent is required.", status=403)
        query = request.GET.copy()
        query["approval_prompt"] = "force"
        request.GET = query
        response = super().get(request, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "application" not in context:
            context["application"] = Application.objects.filter(client_id=self.request.POST.get("client_id", "")).first()
        context["link_url"] = reverse("mcp-link-account") + "?next=" + quote(self.request.get_full_path(), safe="")
        return context

    def form_valid(self, form):
        if not form.cleaned_data["allow"]:
            return super().form_valid(form)
        application = Application.objects.get(client_id=form.cleaned_data["client_id"])
        accounts = list(form.cleaned_data["accounts"])
        names = account_names(accounts)
        with transaction.atomic():
            # Serialize consent changes for this owner/client.
            User.objects.select_for_update().get(pk=self.request.user.pk)
            revoke_tokens(self.request.user, application)
            grant, _ = MCPGrant.objects.update_or_create(owner=self.request.user, oauth_application=application, defaults={
                "name": (application.name or "MCP client")[:100], "token_digest": None,
                "default_account": names[form.cleaned_data["default_account"].pk],
                "allow_writes": "autumn:write" in form.cleaned_data["scope"].split(),
                "expires_at": timezone.now() + timedelta(days=90), "revoked_at": None,
            })
            grant.accounts.all().delete()
            MCPGrantAccount.objects.bulk_create([MCPGrantAccount(grant=grant, user=user, name=names[user.pk]) for user in accounts])
            response = super().form_valid(form)
            location = response.get("Location", "")
            if response.status_code != 302 or "code" not in parse_qs(urlsplit(location).query):
                transaction.set_rollback(True)
            response["Cache-Control"] = "no-store"
            return response


@method_decorator(csrf_exempt, name="dispatch")
class MCPRegistrationView(DynamicClientRegistrationView):
    def post(self, request, *args, **kwargs):
        if _limited(request, "register", 60):
            return JsonResponse({"error": "temporarily_unavailable"}, status=429)
        if len(request.body) > 32768:
            return HttpResponse(status=413)
        return super().post(request, *args, **kwargs)


def _return_to(request):
    target = request.POST.get("next", request.GET.get("next", ""))
    return target if target.startswith("/") and not target.startswith("//") and "\\" not in target else reverse("mcp-connections")


@login_required
@sensitive_post_parameters("password")
def link_account(request):
    target = _return_to(request)
    form = UserLoginForm(request=request, data=request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if _limited(request, "link", 10):
            response = render(request, "core/mcp_link.html", {"form": form, "next": target, "limited": True}, status=429)
            response["Cache-Control"] = "no-store"
            return response
        if form.is_valid():
            account = form.get_user()
            if account != request.user:
                MCPAccountLink.objects.get_or_create(owner=request.user, user=account)
            messages.success(request, f"{account.username} is available to select for your MCP connections.")
            return redirect(target)
    response = render(request, "core/mcp_link.html", {"form": form, "next": target})
    response["Cache-Control"] = "no-store"
    return response


@login_required
def connections(request):
    if request.method == "POST":
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            if request.POST.get("action") == "unlink":
                link = MCPAccountLink.objects.filter(owner=request.user, pk=request.POST.get("id")).first()
                if link:
                    for grant in MCPGrant.objects.filter(owner=request.user, oauth_application__isnull=False,
                                                          accounts__user=link.user):
                        revoke_tokens(request.user, grant.oauth_application)
                        grant.revoked_at = timezone.now()
                        grant.save(update_fields=["revoked_at"])
                    link.delete()
                    messages.success(request, "Account unlinked. Affected connections have been revoked; reconnect to choose accounts again.")
            elif request.POST.get("action") == "revoke":
                grant = MCPGrant.objects.filter(owner=request.user, pk=request.POST.get("id"), oauth_application__isnull=False).first()
                if grant:
                    revoke_tokens(request.user, grant.oauth_application)
                    grant.revoked_at = timezone.now()
                    grant.save(update_fields=["revoked_at"])
                    messages.success(request, "Connection revoked.")
        return redirect("mcp-connections")
    response = render(request, "core/mcp_connections.html", {
        "endpoint": settings.MCP_RESOURCE, "links": request.user.mcp_account_links.select_related("user"),
        "grants": request.user.mcp_grants.filter(oauth_application__isnull=False, revoked_at__isnull=True,
                                               expires_at__gt=timezone.now()).prefetch_related("accounts"),
    })
    response["Cache-Control"] = "no-store"
    return response


oauth_patterns = ([
    path("authorize/", MCPAuthorizationView.as_view(), name="authorize"),
    path("token/", TokenView.as_view(), name="token"),
    path("revoke/", RevokeTokenView.as_view(), name="revoke-token"),
    path("register/", MCPRegistrationView.as_view(), name="dcr-register"),
    path("register/<str:client_id>/", DynamicClientRegistrationManagementView.as_view(), name="dcr-register-management"),
], "oauth2_provider")
