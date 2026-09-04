from django.db import models

from django.contrib.auth.models import User


class Preference(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="preference"
    )

    styles = models.TextField(
        blank=True
    )

    colours = models.TextField(
        blank=True
    )

    stores = models.TextField(
        blank=True
    )

    hobbies = models.TextField(
        blank=True
    )

    def __str__(self):
        return f"{self.user.username}'s Preferences"