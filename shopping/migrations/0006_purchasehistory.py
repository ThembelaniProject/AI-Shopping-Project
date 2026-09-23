from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0005_remove_order_and_order_items"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "product_id",
                    models.CharField(
                        blank=True,
                        max_length=255,
                    ),
                ),
                (
                    "product_name",
                    models.CharField(
                        max_length=255,
                    ),
                ),
                (
                    "store",
                    models.CharField(
                        blank=True,
                        max_length=100,
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        max_length=150,
                    ),
                ),
                (
                    "image_url",
                    models.URLField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "product_url",
                    models.URLField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                    ),
                ),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        default=1,
                    ),
                ),
                (
                    "amount_spent",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                    ),
                ),
                (
                    "purchased_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purchase_history",
                        to="auth.user",
                    ),
                ),
            ],
            options={
                "ordering": ["-purchased_at"],
            },
        ),
    ]
