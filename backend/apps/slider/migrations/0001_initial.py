# Generated by Django 2.1 on 2018-11-13 09:11

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Slider',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image_preview', models.ImageField(blank=True, upload_to='', verbose_name='Images')),
                ('image_alt', models.CharField(blank=True, max_length=255, verbose_name='Images Alt')),
                ('title', models.CharField(max_length=120, verbose_name='Title')),
                ('span', models.CharField(blank=True, max_length=120, verbose_name='Span')),
                ('active', models.BooleanField(default=True, verbose_name='Active')),
                ('ordering', models.IntegerField(verbose_name='Ordering')),
                ('link', models.URLField(blank=True, verbose_name='Link')),
            ],
            options={
                'verbose_name': 'Slider',
                'verbose_name_plural': 'Sliders',
            },
        ),
    ]
