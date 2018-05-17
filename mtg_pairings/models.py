import collections
from typing import List, Set

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import m2m_changed
from django.db.transaction import atomic
from django.dispatch import receiver
from django.urls import reverse


class Player(models.Model):
    name = models.CharField(max_length=256, primary_key=True)

    def __str__(self):
        return self.name


class Performance:
    def __init__(self, player: Player, match_wins: int, wins: int, match_losses: int, losses: int):
        self.player = player
        self.match_wins = match_wins
        self.wins = wins
        self.match_losses = match_losses
        self.losses = losses

    @property
    def _cmp_tuple(self):
        return self.match_wins, -self.match_losses, self.wins, -self.losses

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self._cmp_tuple == other._cmp_tuple
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, self.__class__):
            return self._cmp_tuple < other._cmp_tuple
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, self.__class__):
            return self._cmp_tuple <= other._cmp_tuple
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, self.__class__):
            return self._cmp_tuple > other._cmp_tuple
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, self.__class__):
            return self._cmp_tuple >= other._cmp_tuple
        return NotImplemented

    def __add__(self, other):
        if isinstance(other, self.__class__) and self.player == other.player:
            return self.__class__(
                self.player,
                match_wins=self.match_wins + other.match_wins, wins=self.wins + other.wins,
                match_losses=self.match_losses + other.match_losses, losses=self.losses + other.losses
            )
        return NotImplemented


class Tournament(models.Model):
    name = models.CharField(max_length=256)
    players = models.ManyToManyField(Player, related_name='tournaments')
    date = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.name} on {self.date}'

    @property
    def standing(self) -> List[Performance]:
        players = self.players.all()

        if not self.rounds.exists():
            return [Performance(player, 0, 0, 0, 0) for player in players]

        return sorted(
            (Performance(player,
                         match_wins=self.match_wins(player), wins=self.wins(player),
                         match_losses=self.match_losses(player), losses=self.losses(player)
                         )
             for player in players),
            reverse=True
        )

    @property
    def current_round(self) -> 'Round':
        return self.rounds.latest('number')

    def opponents(self, player: Player) -> Set[Player]:
        return {r.opponent(player) for r in self.rounds.all()}

    @atomic
    def start_first_round(self) -> 'Round':
        first_round = Round.objects.create(tournament=self, number=1)
        players = self.players.all()

        for player_1, player_2 in zip(players[:len(players) // 2], players[len(players) // 2:]):
            Duel.objects.create(player_1=player_1, player_2=player_2, round=first_round)

        return first_round

    @atomic
    def start_next_round(self) -> 'Round':
        """Creates and returns the objects for the next round."""
        current_standing = collections.deque(self.standing)
        assert len(current_standing) == self.players.count(), 'Some players are missing from the current standing'

        next_round = Round(tournament=self, number=self.rounds.count() + 1)

        next_duels = []
        players = set()
        while current_standing:
            performance = current_standing.popleft()

            previous_opponents = self.opponents(performance.player)
            opponent_performance = next(p for p in current_standing if p.player not in previous_opponents)
            current_standing.remove(opponent_performance)

            players.add(performance.player)
            players.add(opponent_performance.player)

            next_duels.append(
                Duel(player_1=performance.player, player_2=opponent_performance.player, round=next_round))

        assert all(p in players for p in self.players.all()), f'Players are missing from {players}'

        next_round.save()
        for duel in next_duels:
            duel.round = next_round
            duel.save()
        return next_round

    def wins(self, player: Player) -> int:
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        return sum(
            r.get_duel_for_player(player).wins_of(player) for r in self.rounds.all()
        )

    def losses(self, player: Player) -> int:
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        return sum(
            r.get_duel_for_player(player).losses_of(player) for r in self.rounds.all()
        )

    def match_wins(self, player: Player) -> int:
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        wins = 0
        for round in self.rounds.all():
            try:
                if round.get_duel_for_player(player).winner == player:
                    wins += 1
            except ValueError:
                pass

        return wins

    def match_losses(self, player: Player) -> int:
        if player not in self.players.all():
            raise ValueError(f'{player} is not playing in {self}')

        losses = 0
        for round in self.rounds.all():
            duel = round.get_duel_for_player(player)
            try:
                if duel.winner != player:
                    losses += 1
            except ValueError:
                pass

        return losses

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

    def get_duel_for_players(self, player_1: Player, player_2: Player) -> 'Duel':
        return self.duels.get(models.Q(player_1=player_1, player_2=player_2) |
                              models.Q(player_1=player_2, player_2=player_1))

    def opponent(self, player: Player) -> Player:
        duel = self.get_duel_for_player(player)
        assert player in (duel.player_1, duel.player_2)
        return duel.player_1 if duel.player_2 == player else duel.player_2


class Duel(models.Model):
    player_1 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='player_ones')
    player_2 = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='player_twos')
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name='duels')

    player_1_wins = models.PositiveSmallIntegerField(default=0)
    player_2_wins = models.PositiveSmallIntegerField(default=0)

    def set_player_performance(self, performance: Performance):
        if performance.player not in (self.player_1, self.player_2):
            raise ValueError('This performance does not belong to this duel')
        if performance.player == self.player_1:
            self.player_1_wins = performance.wins
        else:
            self.player_2_wins = performance.wins

        self.save()

    @property
    def winner(self) -> Player:
        if max(self.player_1_wins, self.player_2_wins) >= settings.MATCH_WINS_NEEDED:
            if self.player_1_wins > self.player_2_wins:
                return self.player_1
            elif self.player_2_wins > self.player_1_wins:
                return self.player_2

        raise ValueError(f'{self} has no winner.')

    def wins_of(self, player: Player) -> int:
        if player == self.player_1:
            return self.player_1_wins
        elif player == self.player_2:
            return self.player_2_wins

        raise ValueError(f'{player} did not play in {self}')

    def losses_of(self, player: Player) -> int:
        if player == self.player_1:
            return self.wins_of(self.player_2)
        elif player == self.player_2:
            return self.wins_of(self.player_1)

        raise ValueError(f'{player} did not play in {self}')

    @property
    def standing(self):
        return (Performance(self.player_1, wins=self.player_1_wins, losses=self.player_2_wins,
                            match_losses=0, match_wins=0),
                Performance(self.player_2, wins=self.player_2_wins, losses=self.player_1_wins,
                            match_wins=0, match_losses=0))

    class Meta:
        unique_together = (
            ('player_1', 'round'),
            ('player_2', 'round')
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
        instance.start_first_round()
