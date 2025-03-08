# core/context_processors.py
import os
import json
from django.conf import settings


def static_version(request):
    version = {}
    static_files = []


    js_dir = os.path.join("core/static/core/js")
    for file in os.listdir(js_dir):
        file_path = os.path.join(js_dir, file)
        static_files.append(file_path)

    css_dir = os.path.join("core/static/core/css")
    for file in os.listdir(css_dir):
        file_path = os.path.join(css_dir, file)
        static_files.append(file_path)

    # img_dir = os.path.join("core/static/core/images")
    # for file in os.listdir(img_dir):
    #     file_path = os.path.join(img_dir, file)
    #     static_files.append(file_path)


    for file in static_files:
        # get base name of the file
        base_name = os.path.basename(file)
        if os.path.exists(file):
            version[base_name] = int(os.path.getmtime(file))
        else:
            version[base_name] = 0

    if settings.DEBUG:
        print("Static version: ", json.dumps(version, indent=4))

    return {'static_version': version}