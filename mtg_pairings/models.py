from typing import List

import attr
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save, pre_save, m2m_changed
from django.db.transaction import atomic
from django.dispatch import receiver
from django.urls import reverse


class Player(models.Model):
    name = models.CharField(max_length=256, primary_key=True)

    def __str__(self):
        return self.name


@attr.s
class Performance:
    player: Player = attr.ib(cmp=False)
    wins: int = attr.ib()
    losses: int = attr.ib()

    def __add__(self, other):
        if isinstance(other, self.__class__) and self.player == other.player:
            return self.__class__(self.player, self.wins + other.wins, self.losses + other.losses)

        return NotImplemented


class Tournament(models.Model):
    name = models.CharField(max_length=256)
    players = models.ManyToManyField(Player, related_name='tournaments')
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} on {self.date}'

    @property
    def standing(self) -> List[Performance]:
        players = self.players.all()

        if not self.rounds.exists():
            return [Performance(player, 0, 0) for player in players]

        return sorted(
            Performance(player, self.wins(player), self.losses(player))
            for player in players
        )

    @property
    def current_round(self) -> 'Round':
        return self.rounds.latest('number')

    def opponents(self, player: Player):
        return {r.get_opponent(player) for r in self.rounds.all()}

    @atomic
    def first_round(self):
        first_round = Round.objects.create(tournament=self, number=1)
        players = self.players.all()

        for player_1, player_2 in zip(players[:len(players)//2], players[len(players)//2:]):
            Duel.objects.create(player_1=player_1, player_2=player_2, round=first_round)

        return first_round

    @atomic
    def next_round(self):
        """Creates and returns the objects for the next round."""
        current_round = self.rounds.count()
        print(f'Creating new round after {current_round}')
        current_standing = self.standing
        print(f'Current standing: {current_standing}')
        assert len(current_standing) == self.players.count(), 'Some players are missing from the current standing'

        next_round = Round.objects.create(tournament=self, number=current_round + 1)

        for performance in current_standing:
            current_standing.remove(performance)

            opponents = self.opponents(performance.player)
            opponents_performance = next(p for p in current_standing if p.player not in opponents)
            current_standing.remove(opponents_performance)

            Duel.objects.create(player_1=performance.player, player_2=opponents_performance.player, round=next_round)

        assert not current_standing, f'{current_standing} is wrong'

        return next_round

    def wins(self, player: Player):
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        return sum(
            r.get_duel_for_player(player).wins_of(player) for r in self.rounds.all()
        )

    def losses(self, player: Player):
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        return sum(
            r.get_duel_for_player(player).losses_of(player) for r in self.rounds.all()
        )

    def get_absolute_url(self):
        return reverse('tournament_detail', args=[str(self.id)])


class Round(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='rounds')
    number = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ('tournament', 'number')

    def __str__(self):
        return f'Round {self.number} of {self.tournament}'

    def get_duel_for_player(self, player: Player) -> 'Duel':
        return self.duels.get(models.Q(player_1=player) | models.Q(player_2=player))

    def get_opponent(self, player: Player) -> Player:
        duel = self.get_duel_for_player(player)
        assert player in (duel.player_1, duel.player_2)
        return duel.player_1 if duel.player_2 == player else duel.player_2


class Duel(models.Model):
    WINS_NEEDED = 3

    player_1 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='player_ones')
    player_2 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='player_twos')
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='duels')

    player_1_wins = models.PositiveSmallIntegerField(default=0)
    player_2_wins = models.PositiveSmallIntegerField(default=0)

    @property
    def winner(self):
        if max(self.player_1_wins, self.player_2_wins) >= self.WINS_NEEDED:
            if self.player_1_wins > self.player_2_wins:
                return self.player_1
            elif self.player_2_wins > self.player_1_wins:
                return self.player_2

        raise ValueError(f'{self} has no winner.')

    def wins_of(self, player: Player):
        if player == self.player_1:
            return self.player_1_wins
        elif player == self.player_2:
            return self.player_2_wins

        raise ValueError(f'{player} did not play in {self}')

    def losses_of(self, player: Player):
        if player == self.player_1:
            return self.wins_of(self.player_2)
        elif player == self.player_2:
            return self.wins_of(self.player_1)

        raise ValueError(f'{player} did not play in {self}')

    @property
    def standing(self):
        return (Performance(self.player_1, self.player_1_wins, self.player_2_wins),
                Performance(self.player_2, self.player_2_wins, self.player_1_wins))

    class Meta:
        unique_together = (
            ('player_1', 'player_2', 'round'),
            ('player_2', 'player_1', 'round')
        )

    def __str__(self):
        return f'{self.player_1}:{self.player_1_wins} vs {self.player_2}:{self.player_2_wins} in {self.round}'


@receiver(m2m_changed, sender=Tournament.players.through)
def assure_players(sender, instance: Tournament, action, **kwargs):
    if action == 'pre_add':
        return

    if instance.players.count() < 2:
        raise ValidationError('A tournament needs at least 2 players.')
    if not instance.rounds.exists():
        instance.first_round()
