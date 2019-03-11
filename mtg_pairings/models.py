import itertools
import math
import typing
from typing import List

import attr
import networkx.algorithms.matching
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.transaction import atomic
from django.dispatch import receiver
from django.urls import reverse


class Player(models.Model):
    name = models.CharField(max_length=256, primary_key=True)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('player_detail', args=[self.name])

    def duels(self):
        return Duel.objects.filter(models.Q(player_1=self) | models.Q(player_2=self))

    def duels_against(self, opponent: "Player"):
        return Duel.objects.filter(
            models.Q(player_1=self, player_2=opponent)
            | models.Q(player_1=opponent, player_2=self)
        )

    @property
    def all_time_performance(self) -> 'Performance':
        return sum(
            (tournament.performance(self) for tournament in self.tournaments.all()),
            Performance(self, 0, 0, 0, 0)  # start
        )


@attr.s
class Performance:
    player: Player = attr.ib(cmp=False)
    match_wins: int = attr.ib()
    match_losses: int = attr.ib()
    wins: int = attr.ib()
    losses: int = attr.ib()

    @attr.s
    class PerformanceDiff:
        match_wins: int = attr.ib(converter=abs)
        match_losses: int = attr.ib(converter=abs)
        wins: int = attr.ib(converter=abs)
        losses: int = attr.ib(converter=abs)

        def __float__(self):
            match_diff = self.match_wins - self.match_losses
            try:
                return match_diff + (self.wins / (self.wins + self.losses))
            except ZeroDivisionError:
                return float(match_diff)

    @property
    def win_percentage(self):
        try:
            return self.wins / (self.wins + self.losses)
        except ZeroDivisionError:
            return 0

    @property
    def match_win_percentage(self):
        try:
            return self.match_wins / (self.match_wins + self.match_losses)
        except ZeroDivisionError:
            return 0

    def __float__(self):
        match_diff = self.match_wins - self.match_losses
        try:
            win_percentage = self.wins / (self.wins + self.losses)
            return match_diff + min(win_percentage, 0.99)
        except ZeroDivisionError:
            return float(match_diff)

    def __add__(self, other):
        if isinstance(other, self.__class__):
            if self.player != other.player:
                raise ValueError('Can only add Performances of the same player.')
            return self.__class__(
                self.player,
                match_wins=self.match_wins + other.match_wins, wins=self.wins + other.wins,
                match_losses=self.match_losses + other.match_losses, losses=self.losses + other.losses
            )
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, self.__class__):
            return self.__class__.PerformanceDiff(
                match_wins=self.match_wins - other.match_wins,
                match_losses=self.match_losses - other.match_losses,
                wins=self.wins - other.wins,
                losses=self.losses - other.losses
            )


def penalty(rank_1: float, rank_2: float) -> float:
    # negative weight to create min matching.
    return -((rank_1 ** 2 - rank_2 ** 2) ** 2)


class Tournament(models.Model):
    name = models.CharField(max_length=256)
    players = models.ManyToManyField(Player, related_name='tournaments')
    date = models.DateField(auto_now_add=True)
    finished = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.name} on {self.date}'

    def duels(self, player: Player = None):
        if player is not None:
            return self.duels().filter(models.Q(player_1=player) | models.Q(player_2=player))

        return Duel.objects.filter(round__tournament=self)

    @property
    def standing(self) -> List[Performance]:
        players = self.players.all()

        if not self.rounds.exists():
            return [Performance(player, 0, 0, 0, 0) for player in players]

        return sorted(
            (Performance(player, match_wins=self.match_wins(player), wins=self.wins(player),
                         match_losses=self.match_losses(player), losses=self.losses(player))
             for player in players),
            key=float, reverse=True
        )

    @property
    def current_round(self) -> 'Round':
        return self.rounds.latest('number')

    def opponents(self, player: Player) -> typing.Iterable[str]:
        return self.duels(player).values_list(
            models.Case(
                models.When(player_1=player, then='player_2'),
                models.When(player_2=player, then='player_1')
            ), flat=True
        )

    @atomic
    def start_first_round(self) -> 'Round':
        all_players = set(self.players.all())
        win_graph = networkx.DiGraph()

        for player in all_players:
            win_graph.add_weighted_edges_from(
                (duel.opponent(player), player, duel.wins_of(player))
                for duel in player.duels()
            )

        ranking = {p: v * 100 for p, v in networkx.pagerank_numpy(win_graph).items()}

        graph = networkx.Graph()

        graph.add_weighted_edges_from(
            (player, opponent, penalty(ranking[player], ranking[opponent]))
            for player, opponent in itertools.combinations(all_players, r=2)
        )

        matching = networkx.algorithms.matching.max_weight_matching(graph, maxcardinality=True)
        next_round = Round.objects.create(tournament=self, number=1)
        for player_1, player_2 in matching:
            Duel.objects.create(round=next_round, player_1=player_1, player_2=player_2)

        return next_round

    @atomic
    def start_next_round(self) -> 'Round':
        """Creates and returns the objects for the next round."""
        all_players = set(self.players.all())
        possible_matchings = set(map(frozenset, itertools.combinations(all_players, r=2)))
        previous_duels = set(self.duels())
        previous_matchings = set(
            frozenset((duel.player_1, duel.player_2))
            for duel in previous_duels
        )

        win_graph = networkx.DiGraph()
        weighted_edges = []

        for duel in previous_duels:
            weighted_edges.extend([
                (duel.player_2, duel.player_1, duel.player_1_wins),
                (duel.player_1, duel.player_2, duel.player_2_wins)
            ])

        win_graph.add_weighted_edges_from(weighted_edges)

        # try to avoid floating point errors when subtracting later by increasing magnitudes
        ranking = {p: v * 100 for p, v in networkx.pagerank_numpy(win_graph).items()}
        graph = networkx.Graph()

        graph.add_weighted_edges_from([
            (player, opponent, penalty(ranking[player], ranking[opponent]))
            for player, opponent in possible_matchings - previous_matchings
         ]
        )

        next_round = Round.objects.create(tournament=self, number=self.current_round.number + 1)
        matching = networkx.algorithms.matching.max_weight_matching(graph, maxcardinality=True)
        matched_players = set()
        for player_1, player_2 in matching:
            assert player_2 not in self.opponents(player_1)
            assert player_1 not in self.opponents(player_2)
            matched_players.update({player_1, player_2})
            Duel.objects.create(player_1=player_1, player_2=player_2, round=next_round)

        player_diff = all_players - matched_players
        assert not player_diff, f'{player_diff} have not been matched'
        return next_round

    def finish(self):
        self.finished = True
        self.save()

    def wins(self, player: Player) -> int:
        aggregate = self.duels(player).aggregate(wins=models.Sum(
            models.Case(models.When(player_1=player, then='player_1_wins'),
                        models.When(player_2=player, then='player_2_wins'))))

        return aggregate['wins'] if aggregate['wins'] else 0

    def losses(self, player: Player) -> int:
        aggregate = self.duels(player).aggregate(losses=models.Sum(
            models.Case(models.When(player_1=player, then='player_2_wins'),
                        models.When(player_2=player, then='player_1_wins'))))
        return aggregate['losses'] if aggregate['losses'] else 0

    def _match_win_query(self, player: Player):
        won_as_player_1 = models.Q(player_1=player, player_1_wins__gt=models.F('player_2_wins'))
        won_as_player_2 = models.Q(player_2=player, player_2_wins__gt=models.F('player_1_wins'))
        return won_as_player_1 | won_as_player_2

    def _match_lose_query(self, player: Player):
        lost_as_player_1 = models.Q(player_1=player, player_1_wins__lt=models.F('player_2_wins'))
        lost_as_player_2 = models.Q(player_2=player, player_2_wins__lt=models.F('player_1_wins'))
        return lost_as_player_1 | lost_as_player_2

    def match_wins(self, player: Player) -> int:
        return self.duels(player).filter(self._match_win_query(player)).count()

    def match_losses(self, player: Player) -> int:
        return self.duels(player).filter(self._match_lose_query(player)).count()

    def performance(self, player: Player):
        return Performance(player,
                           match_wins=self.match_wins(player), wins=self.wins(player),
                           match_losses=self.match_losses(player), losses=self.losses(player)
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

    def opponent(self, player: Player):
        if player == self.player_1:
            return self.player_2
        if player == self.player_2:
            return self.player_1

        raise ValueError(f'{player} did not play in {self}')

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
            ('player_2', 'round'),
        )

    def __str__(self):
        return f'{self.player_1}:{self.player_1_wins} vs {self.player_2}:{self.player_2_wins} in {self.round}'


@receiver(models.signals.m2m_changed, sender=Tournament.players.through)
def assure_players(sender, instance: Tournament, action, **kwargs):
    if action == 'pre_add':
        return

    if instance.players.count() < 2 or instance.players.count() % 2:
        raise ValidationError('A tournament needs at least 2 players and an even number of players.')
    if not instance.rounds.exists():
        instance.start_first_round()
