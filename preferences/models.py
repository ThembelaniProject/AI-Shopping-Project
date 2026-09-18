
from django.db import models
from django.contrib.auth.models import User


class Preference(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="preference"
    )

    styles = models.JSONField(
        default=list,
        blank=True
    )

    colours = models.JSONField(
        default=list,
        blank=True
    )

    stores = models.JSONField(
        default=list,
        blank=True
    )

    hobbies = models.JSONField(
        default=list,
        blank=True
    )

    def __str__(self):
        return f"{self.user.username}'s Preferences"

