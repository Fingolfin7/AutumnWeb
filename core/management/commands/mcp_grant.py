"""Create/list/revoke a dedicated MCP credential without using Autumn API tokens."""
import hashlib
import json
import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import MCPGrant, MCPGrantAccount


class Command(BaseCommand):
    help = "Create, list, or revoke account-scoped MCP grants. Create prints the secret once."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["create", "list", "revoke"])
        parser.add_argument("--owner")
        parser.add_argument("--name", default="MCP connector")
        parser.add_argument("--account", action="append", default=[], help="Alias=username; repeat for each account")
        parser.add_argument("--default-account")
        parser.add_argument("--allow-writes", action="store_true")
        parser.add_argument("--expires-days", type=int, default=90)
        parser.add_argument("--grant-id", type=int)

    def handle(self, action, **options):
        if action == "list":
            grants = MCPGrant.objects.all()
            if options["owner"]:
                grants = grants.filter(owner__username=options["owner"])
            self.stdout.write(json.dumps([
                {"id": grant.id, "name": grant.name, "owner": grant.owner.username,
                 "accounts": list(grant.accounts.values_list("name", flat=True)),
                 "allow_writes": grant.allow_writes, "expires_at": grant.expires_at.isoformat(),
                 "revoked": grant.revoked_at is not None} for grant in grants.select_related("owner")
            ]))
            return
        if action == "revoke":
            if not options["grant_id"]:
                raise CommandError("--grant-id is required")
            if not MCPGrant.objects.filter(pk=options["grant_id"]).update(revoked_at=timezone.now()):
                raise CommandError("Grant not found")
            self.stdout.write("Revoked")
            return
        if not options["owner"] or not options["account"]:
            raise CommandError("--owner and at least one --account are required")
        if not 1 <= options["expires_days"] <= 365:
            raise CommandError("--expires-days must be between 1 and 365")
        if not 1 <= len(options["name"]) <= 100:
            raise CommandError("--name must contain 1 to 100 characters")
        try:
            owner = User.objects.get(username=options["owner"], is_active=True)
            bindings = []
            for value in options["account"]:
                alias, username = value.split("=", 1)
                if not alias.strip() or len(alias) > 128:
                    raise ValueError()
                bindings.append((alias, User.objects.get(username=username, is_active=True)))
        except (User.DoesNotExist, ValueError):
            raise CommandError("Invalid owner or account. Use Alias=active_username.") from None
        names = [alias.casefold() for alias, _ in bindings]
        if len(set(names)) != len(names):
            raise CommandError("Account names must be unique, ignoring case")
        default = options["default_account"] or bindings[0][0]
        if default.casefold() not in names:
            raise CommandError("Default account must be included in this grant")
        default = bindings[names.index(default.casefold())][0]
        token = "autumn_mcp_" + secrets.token_urlsafe(32)
        with transaction.atomic():
            grant = MCPGrant.objects.create(
                owner=owner, name=options["name"], token_digest=hashlib.sha256(token.encode()).hexdigest(),
                default_account=default, allow_writes=options["allow_writes"],
                expires_at=timezone.now() + timedelta(days=options["expires_days"]),
            )
            MCPGrantAccount.objects.bulk_create([
                MCPGrantAccount(grant=grant, name=alias, user=user) for alias, user in bindings
            ])
        self.stdout.write(json.dumps({"grant_id": grant.id, "token": token,
                                     "expires_at": grant.expires_at.isoformat()}))
