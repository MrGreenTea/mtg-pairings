from django.db import models


# Create your models here.
class Player(models.Model):
    name = models.CharField(max_length=256)


class Duel(models.Model):
    player_1 = models.ForeignKey(Player, on_delete=models.CASCADE)
    player_2 = models.ForeignKey(Player, on_delete=models.CASCADE)

    class Meta:
        unique_together = (
            ('player_1', 'player_2'),
            ('player_2', 'player_1')
        )


class Tournament(models.Model):
    players = models.ManyToManyField(Player, related_name='tournaments')


class Round(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='rounds')
    number = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ('tournament', 'number')
