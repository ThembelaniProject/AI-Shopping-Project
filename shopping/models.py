from django.conf import settings
from django.db import models


class Order(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )

    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30)

    address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)

    payment_method = models.CharField(
        max_length=30,
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    shipping_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return f"Order #{self.id} - {self.user}"
    
class OrderItem(models.Model):

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product_id = models.PositiveIntegerField()

    product_name = models.CharField(
        max_length=255,
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    quantity = models.PositiveIntegerField()

    item_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    def __str__(self):
        return self.product_name
