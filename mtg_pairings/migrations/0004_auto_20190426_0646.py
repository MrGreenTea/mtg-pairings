# Generated by Django 2.0.13 on 2019-04-26 06:46

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mtg_pairings', '0003_tournament_teams'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='player',
            options={'ordering': ('name',)},
        ),
    ]
