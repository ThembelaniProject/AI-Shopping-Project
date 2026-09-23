"""Shopping app models.

The shopping application does not process payments, checkout, or retailer
orders. It stores user-confirmed purchases only so students can track
spending and view purchase history.
"""

from django.conf import settings
from django.db import models


class PurchaseHistory(models.Model):
    """A purchase manually confirmed by the student.

    The purchase happens on the external retailer website. This record is
    only the student's spending-history entry and is not a retailer order.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="purchase_history",
    )

    product_id = models.CharField(
        max_length=255,
        blank=True,
    )

    product_name = models.CharField(
        max_length=255,
    )

    store = models.CharField(
        max_length=100,
        blank=True,
    )

    category = models.CharField(
        max_length=150,
        blank=True,
    )

    image_url = models.URLField(
        blank=True,
        null=True,
    )

    product_url = models.URLField(
        blank=True,
        null=True,
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    quantity = models.PositiveIntegerField(
        default=1,
    )

    amount_spent = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    purchased_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-purchased_at"]

    def __str__(self):
        return f"{self.product_name} - R{self.amount_spent}"

