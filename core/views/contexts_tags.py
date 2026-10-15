from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from core.models import Context
from core.utils import set_active_context as store_active_context


@login_required
def switch_context(request):
    """
    Update the active context in the session based on a dropdown selection.

    Named switch_context rather than set_active_context so it cannot shadow
    the core.utils helper it calls. The URL keeps its original name.
    """
    if request.method == "POST":
        context_id = request.POST.get("context_id") or "all"
        # Validate context_id when not 'all'
        if context_id != "all":
            try:
                Context.objects.get(id=int(context_id), user=request.user)
            except (Context.DoesNotExist, ValueError, TypeError):
                context_id = "all"
        store_active_context(request, context_id)
        profile = request.user.profile
        profile.active_context_id = None if context_id == "all" else int(context_id)
        profile.save(update_fields=["active_context"])
        next_url = (
            request.POST.get("next")
            or request.META.get("HTTP_REFERER")
            or reverse("home")
        )
        # Never bounce to a URL supplied by someone else's page.
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = reverse("home")
        return redirect(next_url)

    # Fallback GET handler – treat like resetting to All
    store_active_context(request, "all")
    profile = request.user.profile
    profile.active_context = None
    profile.save(update_fields=["active_context"])
    return redirect("home")
