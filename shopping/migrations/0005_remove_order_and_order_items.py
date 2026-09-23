from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0004_order_updated_at_alter_order_shipping_total"),
    ]

    operations = [
        migrations.DeleteModel(
            name="OrderItem",
        ),
        migrations.DeleteModel(
            name="Order",
        ),
    ]
