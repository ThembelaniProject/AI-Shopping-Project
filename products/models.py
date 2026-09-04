from django.db import models
from django.utils import timezone


class Product(models.Model):
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=255, blank=True)
    colour = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=100, blank=True)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    shipping_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    stock = models.PositiveIntegerField(default=0)

    store = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)

    description = models.TextField(blank=True)
    source = models.URLField(blank=True)

    created_at = models.DateTimeField(
        default=timezone.now
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    @property
    def total_cost(self):
        return self.price + self.shipping_cost

    def __str__(self):
        return self.name