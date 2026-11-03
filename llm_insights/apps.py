from django.apps import AppConfig


class LlmInsightsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'llm_insights'

    def ready(self):
        from llm_insights import attachments  # noqa: F401  (file-deletion signal)
