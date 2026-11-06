"""Stable bookmarks for the pages now collected in Settings."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def settings_redirect(request, section):
    query = request.META.get("QUERY_STRING", "")
    return redirect(f"/settings/{section}/" + (f"?{query}" if query else ""))
