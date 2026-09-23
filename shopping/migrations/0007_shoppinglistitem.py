from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [
        ("shopping", "0006_purchasehistory"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShoppingListItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("product_id", models.CharField(blank=True, max_length=255)),
                ("product_name", models.CharField(max_length=255)),
                ("store", models.CharField(blank=True, max_length=100)),
                ("category", models.CharField(blank=True, max_length=150)),
                ("image_url", models.URLField(blank=True, null=True)),
                ("product_url", models.URLField(blank=True, null=True)),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shopping_list_items", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-added_at"]},
        ),
    ]
