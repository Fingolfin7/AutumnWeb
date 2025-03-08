# core/context_processors.py
import os
import json
from django.conf import settings


def static_version(request):
    version = {}

    # Use STATIC_ROOT in production, otherwise look in app's static directory
    base_static = settings.STATIC_ROOT if not settings.DEBUG else os.path.join("core", "static")

    # Define directories to scan
    static_dirs = {
        'js': os.path.join(base_static, "core", "js"),
        'css': os.path.join(base_static, "core", "css"),
    }

    print("Static directories: ", static_dirs)

    # Scan each directory
    for dir_path in static_dirs.values():
        if os.path.exists(dir_path):
            for file in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file)
                if os.path.isfile(file_path):
                    basename = os.path.basename(file_path)
                    version[basename] = int(os.path.getmtime(file_path))

    if settings.DEBUG:
        print("Static version: ", json.dumps(version, indent=4))

    return {'static_version': version}