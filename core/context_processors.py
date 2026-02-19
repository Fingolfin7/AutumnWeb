# core/context_processors.py
import os
import json
from django.conf import settings
from django.core.cache import cache
from core.utils import get_active_context
from core.models import Context


def static_version(request):
    # Try to get versions from cache first
    cache_key = 'static_file_versions'
    version = cache.get(cache_key)

    if version:  # If cache hit, return cached version
        return {'static_version': version}

    version = {}

    # Use STATIC_ROOT in production, otherwise look in app's static directory
    base_static = settings.STATIC_ROOT if not settings.DEBUG else os.path.join("core", "static")

    static_dirs = {
        'js': os.path.join(base_static, "core", "js"),
        'css': os.path.join(base_static, "core", "css"),
    }

    # Scan each directory (including subdirectories)
    for dir_path in static_dirs.values():
        if os.path.exists(dir_path):
            for entry in os.listdir(dir_path):
                entry_path = os.path.join(dir_path, entry)
                if os.path.isfile(entry_path):
                    name, ext = os.path.splitext(entry)
                    mtime = int(os.path.getmtime(entry_path))
                    version[name] = max(version.get(name, 0), mtime)
                elif os.path.isdir(entry_path):
                    # For subdirectories, use the max mtime of all files
                    # as the version key (e.g. "charts" for js/charts/)
                    max_mtime = 0
                    for sub_file in os.listdir(entry_path):
                        sub_path = os.path.join(entry_path, sub_file)
                        if os.path.isfile(sub_path):
                            max_mtime = max(max_mtime, os.path.getmtime(sub_path))
                    if max_mtime:
                        version[entry] = max(version.get(entry, 0), int(max_mtime))

    # Cache the version dictionary and set timeout
    timeout = settings.STATIC_VERSION_CACHE_TIMEOUT['debug'] if settings.DEBUG \
        else settings.STATIC_VERSION_CACHE_TIMEOUT['production']

    cache.set(cache_key, version, timeout)

    # if settings.DEBUG:
    #     print("Static directories: ", static_dirs)
    #     print("Static version: ", json.dumps(version, indent=4))

    return {'static_version': version}


def active_context(request):
    """
    Inject the user's contexts and currently active context into all templates.
    """
    if not request.user.is_authenticated:
        return {}

    context_obj, mode = get_active_context(request)
    user_contexts = Context.objects.filter(user=request.user).order_by('name')

    return {
        'active_context': context_obj,
        'active_context_mode': mode,
        'user_contexts': user_contexts,
    }