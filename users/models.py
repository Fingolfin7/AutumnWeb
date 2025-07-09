import os
from django.db import models
from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO
from PIL import Image, ImageSequence


# make the email field for the user model unique
User._meta.get_field('email')._unique = True

# Create your models here.
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    image = models.ImageField(default='default.jpg', upload_to='profile_pics')
    background_image = models.ImageField(upload_to='background_pics', null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} Profile"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
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