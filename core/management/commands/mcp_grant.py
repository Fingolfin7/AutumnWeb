"""Administrative listing/revocation; users connect through OAuth sign-in."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import MCPGrant
from core.mcp_oauth import revoke_tokens


class Command(BaseCommand):
    help = "List or revoke MCP connections. New connections require user sign-in and consent."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "revoke"])
        parser.add_argument("--owner")
        parser.add_argument("--grant-id", type=int)

    def handle(self, action, **options):
        if action == "list":
            grants = MCPGrant.objects.select_related("owner")
            if options["owner"]:
                grants = grants.filter(owner__username=options["owner"])
            self.stdout.write(json.dumps([
                {"id": grant.id, "name": grant.name, "owner": grant.owner.username,
                 "accounts": list(grant.accounts.values_list("name", flat=True)),
                 "allow_writes": grant.allow_writes, "expires_at": grant.expires_at.isoformat(),
                 "revoked": grant.revoked_at is not None} for grant in grants
            ]))
            return
        if not options["grant_id"]:
            raise CommandError("--grant-id is required")
        with transaction.atomic():
            grant = MCPGrant.objects.select_for_update().filter(pk=options["grant_id"]).first()
            if not grant:
                raise CommandError("Grant not found")
            if grant.oauth_application_id:
                revoke_tokens(grant.owner, grant.oauth_application)
            grant.revoked_at = timezone.now()
            grant.save(update_fields=["revoked_at"])
        self.stdout.write("Revoked")
