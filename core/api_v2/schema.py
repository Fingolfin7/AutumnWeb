def v2_endpoints_only(endpoints):
    return [endpoint for endpoint in endpoints if endpoint[0].startswith("/api/v2/")]
