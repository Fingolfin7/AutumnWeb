from llm_insights.services.streaming import stream_insights_response


def user_has_insights_access(user):
    profile = getattr(user, "profile", None)
    return bool(profile and profile.insights_access_enabled)


def stream_insights(request, chat_id=None):
    """The Insights chat stream (SSE). The page itself is the React app."""
    return stream_insights_response(request, chat_id, user_has_insights_access)
