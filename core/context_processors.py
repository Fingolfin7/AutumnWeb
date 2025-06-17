# core/context_processors.py
import os
import json
from django.conf import settings
from django.core.cache import cache


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

    # Scan each directory
    for dir_path in static_dirs.values():
        if os.path.exists(dir_path):
            for file in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file)
                if os.path.isfile(file_path):
                    basename = os.path.basename(file_path)
                    name, ext = os.path.splitext(basename)    # e.g. "style", ".css"
                    version[name] = int(os.path.getmtime(file_path))

    # Cache the version dictionary and set timeout
    timeout = settings.STATIC_VERSION_CACHE_TIMEOUT['debug'] if settings.DEBUG \
        else settings.STATIC_VERSION_CACHE_TIMEOUT['production']

    cache.set(cache_key, version, timeout)

    # if settings.DEBUG:
    #     print("Static directories: ", static_dirs)
    #     print("Static version: ", json.dumps(version, indent=4))

    return {'static_version': version}