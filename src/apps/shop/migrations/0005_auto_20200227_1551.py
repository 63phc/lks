# Generated by Django 3.0.2 on 2020-02-27 12:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0004_auto_20200223_1746"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ordercart",
            name="address",
            field=models.CharField(
                blank=True, max_length=256, null=True, verbose_name="Address"
            ),
        ),
    ]