"""Shopping app models.

The shopping application does not process payments, checkout, or retailer
orders. It stores user-confirmed purchases and planned shopping-list items.
"""

from django.conf import settings
from django.db import models


class PurchaseHistory(models.Model):
    """A purchase manually confirmed by the student."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchase_history")
    product_id = models.CharField(max_length=255, blank=True)
    product_name = models.CharField(max_length=255)
    store = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=150, blank=True)
    image_url = models.URLField(blank=True, null=True)
    product_url = models.URLField(blank=True, null=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    amount_spent = models.DecimalField(max_digits=12, decimal_places=2)
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchased_at"]

    def __str__(self):
        return f"{self.product_name} - R{self.amount_spent}"


class ShoppingListItem(models.Model):
    """A product the student intends to buy."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shopping_list_items")
    product_id = models.CharField(max_length=255, blank=True)
    product_name = models.CharField(max_length=255)
    store = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=150, blank=True)
    image_url = models.URLField(blank=True, null=True)
    product_url = models.URLField(blank=True, null=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]

    @property
    def estimated_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"
