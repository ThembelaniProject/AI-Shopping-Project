from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0008_shoppinglistaddition"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchasehistory",
            name="store",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="shoppinglistaddition",
            name="store",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="shoppinglistitem",
            name="store",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
