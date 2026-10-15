from rest_framework.renderers import JSONRenderer


class EventStreamRenderer(JSONRenderer):
    """Negotiate SSE while leaving successful streams to StreamingHttpResponse."""

    media_type = "text/event-stream"
    format = "event-stream"
    render_style = "text"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        payload = super().render(data, accepted_media_type, renderer_context)
        if not payload:
            return payload
        return b"data: " + payload + b"\n\n"
