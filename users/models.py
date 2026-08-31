from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.files.storage import default_storage
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from cryptography.fernet import Fernet
from django.conf import settings


# make the email field for the user model unique
User._meta.get_field('email')._unique = True

# Helper to get a stable fernet key (derive from SECRET_KEY)
_DEF_FERNET = None

DEFAULT_FILTER_UNIT_CHOICES = (
    ('days', 'Days'),
    ('weeks', 'Weeks'),
    ('months', 'Months'),
    ('years', 'Years'),
    ('month_to_date', 'Month to date'),
    ('quarter_to_date', 'Quarter to date'),
    ('year_to_date', 'Year to date'),
)


def validate_iana_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValidationError("Enter a valid IANA timezone.")

def get_fernet():
    global _DEF_FERNET
    if _DEF_FERNET is None:
        # Derive a 32-byte base64 urlsafe key from SECRET_KEY deterministically
        import hashlib, base64
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
        _DEF_FERNET = Fernet(key)
    return _DEF_FERNET


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    image = models.ImageField(default='default.jpg', upload_to='profile_pics')
    timezone = models.CharField(
        max_length=64,
        default="Europe/Prague",
        db_default="Europe/Prague",
        validators=[validate_iana_timezone],
    )
    background_image = models.ImageField(upload_to='background_pics', null=True, blank=True)
    background_dimming = models.PositiveSmallIntegerField(default=55)
    automatic_background = models.BooleanField(default=False)  # Automatically set background image
    bing_background = models.BooleanField(default=False)  # Use Bing's daily image (if automatic_background is True)
    nasa_apod_background = models.BooleanField(default=False)  # Use NASA's Astronomy Picture of the Day (if automatic_background is True)
    # Encrypted API key fields (nullable)
    gemini_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)
    openai_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)
    openai_chatgpt_token_enc = models.BinaryField(null=True, blank=True, editable=False)
    claude_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)
    ai_features_enabled = models.BooleanField(
        # Off by default so a fresh account must not get AI access until the
        # operator grants it.
        default=False,
        verbose_name="AI features",
        help_text="Allow this account to use Insights and configure AI provider credentials.",
    )
    default_filter_value = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="How far the default date filter looks back from today.",
    )
    default_filter_unit = models.CharField(
        max_length=15,
        choices=DEFAULT_FILTER_UNIT_CHOICES,
        default='months',
    )
    insights_default_filter_value = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="How far the default Insights date filter looks back from today.",
    )
    insights_default_filter_unit = models.CharField(
        max_length=15,
        choices=DEFAULT_FILTER_UNIT_CHOICES,
        default='months',
    )
    default_chart_project_count = models.PositiveSmallIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Number of projects shown individually before the remainder are grouped as Other.",
    )

    def __str__(self):
        return f"{self.user.username} Profile"

    @property
    def has_ai_credentials(self):
        """Whether this profile has a provider key or a Codex login."""
        return any(
            getattr(self, field_name)
            for field_name in (
                "gemini_api_key_enc",
                "openai_api_key_enc",
                "openai_chatgpt_token_enc",
                "claude_api_key_enc",
            )
        )

    @property
    def insights_access_enabled(self):
        """Whether the user can see or use Insights."""
        return bool(self.ai_features_enabled and self.has_ai_credentials)

    def _filter_date_range(
        self,
        value: int,
        unit: str,
        reference_date: date | datetime | None = None,
    ) -> tuple[date, date]:
        if reference_date is None:
            end_date = timezone.localdate()
        elif isinstance(reference_date, datetime):
            if timezone.is_aware(reference_date):
                reference_date = timezone.localtime(reference_date)
            end_date = reference_date.date()
        else:
            end_date = reference_date

        if unit == 'month_to_date':
            return end_date.replace(day=1), end_date
        if unit == 'quarter_to_date':
            quarter_start_month = ((end_date.month - 1) // 3) * 3 + 1
            return end_date.replace(month=quarter_start_month, day=1), end_date
        if unit == 'year_to_date':
            return end_date.replace(month=1, day=1), end_date

        value = max(1, value)
        if unit not in {'days', 'weeks', 'months', 'years'}:
            unit = 'months'

        start_date = end_date - relativedelta(**{unit: value})
        return start_date, end_date

    def default_filter_date_range(
        self, reference_date: date | datetime | None = None
    ) -> tuple[date, date]:
        """Return the app's configured default date range."""
        return self._filter_date_range(
            self.default_filter_value,
            self.default_filter_unit,
            reference_date,
        )

    def insights_default_filter_date_range(
        self, reference_date: date | datetime | None = None
    ) -> tuple[date, date]:
        """Return the configured default date range for new Insights chats."""
        return self._filter_date_range(
            self.insights_default_filter_value,
            self.insights_default_filter_unit,
            reference_date,
        )

    @property
    def background_dimming_alpha(self):
        value = max(0, min(85, self.background_dimming))
        return f"{value / 100:.2f}"

    # Encryption / Decryption helpers
    def set_api_key(self, provider: str, raw_key: str | None):
        field_map = {
            'gemini': 'gemini_api_key_enc',
            'openai': 'openai_api_key_enc',
            'openai_chatgpt': 'openai_chatgpt_token_enc',
            'claude': 'claude_api_key_enc',
        }
        fname = field_map.get(provider.lower())
        if not fname:
            raise ValueError('Unsupported provider')
        if not raw_key:
            setattr(self, fname, None)
        else:
            f = get_fernet()
            setattr(self, fname, f.encrypt(raw_key.encode()))

    def get_api_key(self, provider: str) -> str | None:
        field_map = {
            'gemini': 'gemini_api_key_enc',
            'openai': 'openai_api_key_enc',
            'openai_chatgpt': 'openai_chatgpt_token_enc',
            'claude': 'claude_api_key_enc',
        }
        fname = field_map.get(provider.lower())
        if not fname:
            return None
        data = getattr(self, fname)
        if not data:
            return None
        f = get_fernet()
        try:
            # Convert to bytes explicitly - PostgreSQL returns memoryview for BinaryField
            return f.decrypt(bytes(data)).decode()
        except Exception:
            return None

    # create a getter for the user image that returns the default image if no image is set/is missing
    @property
    def image_url(self):
        if self.image:
            try:
                return self.image.url
            except Exception:
                pass
        return default_storage.url("default.jpg")
