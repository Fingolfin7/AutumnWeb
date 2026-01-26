import os
from django.db import models
from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO
from PIL import Image, ImageSequence
from cryptography.fernet import Fernet
from django.conf import settings


# make the email field for the user model unique
User._meta.get_field('email')._unique = True

# Helper to get a stable fernet key (derive from SECRET_KEY)
_DEF_FERNET = None

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
    background_image = models.ImageField(upload_to='background_pics', null=True, blank=True)
    automatic_background = models.BooleanField(default=False)  # Automatically set background image
    bing_background = models.BooleanField(default=False)  # Use Bing's daily image (if automatic_background is True)
    nasa_apod_background = models.BooleanField(default=False)  # Use NASA's Astronomy Picture of the Day (if automatic_background is True)
    # Encrypted API key fields (nullable)
    gemini_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)
    openai_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)
    claude_api_key_enc = models.BinaryField(null=True, blank=True, editable=False)

    def __str__(self):
        return f"{self.user.username} Profile"

    # Encryption / Decryption helpers
    def set_api_key(self, provider: str, raw_key: str | None):
        field_map = {
            'gemini': 'gemini_api_key_enc',
            'openai': 'openai_api_key_enc',
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
            return f.decrypt(data).decode()
        except Exception:
            return None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if not os.path.exists(self.image.path):
            return  # image file does not exist

        img = Image.open(self.image)

        if img.format == 'GIF':
            # trying to trigger the save method of the image field so that django_cleanups can clean up the old image
            self.image = self.resize_gif(img)

        elif img.format != 'GIF' and (img.height > 450 or img.width > 450):
            img_width = img.size[0] if img.size[0] < 450 else 450
            img_height = img.size[1] if img.size[1] < 450 else 450

            output_size = (img_width, img_height)
            img.thumbnail(output_size)
            img.save(self.image.path)

    # create a getter for the user image that returns the default image if no image is set/is missing
    @property
    def image_url(self):
        if self.image and os.path.exists(self.image.path) and hasattr(self.image, 'url'):
            return self.image.url
        return f"{settings.MEDIA_URL}default.jpg"

    def resize_gif(self, img):
        """
        Resize a gif image by resizing each frame and then reassembling the frames into a new gif
        """

        frame_width = img.size[0] if img.size[0] < 450 else 450
        frame_height = img.size[1] if img.size[1] < 450 else 450

        if frame_width == img.size[0] and frame_height == img.size[1]: # if the image is already the correct size
            return self.image

        frames = []
        durations = []  # Store frame durations
        disposal_methods = []  # Store disposal methods

        for frame in ImageSequence.Iterator(img):
            # Resize the frame
            frame = frame.resize((frame_width, frame_height))

            # Extract and store the frame duration and disposal method
            durations.append(frame.info.get("duration", 100))  # Default duration is 100 ms
            disposal_methods.append(frame.info.get("disposal_method", 0))  # Default disposal method is 0

            frames.append(frame)

        # Create a new GIF with frame durations and disposal methods
        with BytesIO() as output_buffer:
            frames[0].save(
                output_buffer,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                disposal=disposal_methods,
                loop=img.info.get("loop", 0)  # Copy the loop count from the original
            )

            buffer = BytesIO(output_buffer.getvalue())

        return InMemoryUploadedFile(
            buffer,
            'ImageField',
            os.path.normpath(self.image.path),
            'image/gif',
            buffer.getbuffer().nbytes,
            None
        )