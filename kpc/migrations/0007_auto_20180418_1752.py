# Generated by Django 2.0.4 on 2018-04-18 17:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kpc', '0006_auto_20180418_1537'),
    ]

    operations = [
        migrations.AlterField(
            model_name='certificate',
            name='number',
            field=models.PositiveIntegerField(help_text='USKPA Certificate ID number', unique=True),
        ),
        migrations.AlterField(
            model_name='historicalcertificate',
            name='number',
            field=models.PositiveIntegerField(db_index=True, help_text='USKPA Certificate ID number'),
        ),
    ]
