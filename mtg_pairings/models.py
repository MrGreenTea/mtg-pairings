import base64
import bisect
import collections
import itertools
import typing
from typing import List

import attr
import networkx.algorithms.matching
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, IntegrityError
from django.db.transaction import atomic
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.auth.models import User, Group


class Player(models.Model):
    name = models.CharField(max_length=256, primary_key=True)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True)
    _FREEWIN: "Player" = None

    def __str__(self):
        return self.name

    @classmethod
    def FREEWIN(cls) -> "Player":
        if cls._FREEWIN is not None:
            return cls._FREEWIN
        cls._FREEWIN, created = cls.objects.get_or_create(name="FREE WIN")

    @classmethod
    def without_freewin(cls):
        return cls.objects.exclude(name=cls.FREEWIN().name)

    def get_absolute_url(self):
        return reverse('player_detail', args=[self.name])

    def duels(self, from_duels=None):
        if from_duels is None:
            from_duels = Duel.objects

        return from_duels.filter(models.Q(player_1=self) | models.Q(player_2=self))

    def duels_against(self, opponent: "Player"):
        return Duel.objects.filter(
            models.Q(player_1=self, player_2=opponent)
            | models.Q(player_1=opponent, player_2=self)
        )

    @property
    def all_time_performance(self) -> 'Performance':
        duels = self.duels(Duel.without_freewins())

        returned_standing = standing(duels, [self])
        assert len(returned_standing) == 1, f"Standing contains for players than {self}"

        return returned_standing[0]

    @classmethod
    def all_time_standing(cls, duels=None, players=None):
        if duels is None:
            duels = Duel.without_freewins().select_related("round__tournament__players")

        if players is None:
            players = duels.values_list("player_1", flat=True).union(duels.values_list("player_2", flat=True))
            players = Player.objects.filter(name__in=players)

        return standing(duels, players)

    @classmethod
    def all_time_ranking(cls, draw=False):
        duels = Duel.without_freewins().select_related("round__tournament__players")

        players = duels.values_list("player_1", flat=True).union(duels.values_list("player_2", flat=True))
        players = Player.objects.filter(name__in=players)

        calculated_standing = cls.all_time_standing(duels=duels, players=players)
        pageranking, visualization = ranking(duels, players, draw=draw)

        return {
            "ranking": sorted(calculated_standing, key=lambda k: pageranking[k.player], reverse=True),
            "graph": visualization
        }


@attr.s(cmp=False)
class Performance:
    player: Player = attr.ib()
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
            return 0.0

    @property
    def match_win_percentage(self):
        try:
            return self.match_wins / (self.match_wins + self.match_losses)
        except ZeroDivisionError:
            return 0.0

    def __float__(self):
        return self.match_win_percentage * 100 + self.win_percentage

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

    def __gt__(self, other):
        return float(self) > other

    def __lt__(self, other):
        return float(self) < other

    def __eq__(self, other):
        return float(self) == float(other)


def standing(duels, players) -> List[Performance]:
    player_standings: List[Performance] = []

    for player in players:
        aggregate = duels.aggregate(
            match_wins=models.Count("round", filter=models.Q(player_1=player, player_1_wins__gt=models.F(
                "player_2_wins")) | models.Q(player_2=player, player_2_wins__gt=models.F("player_1_wins")),
                                    distinct=True),
            match_losses=models.Count("round", filter=models.Q(player_1=player, player_2_wins__gt=models.F(
                "player_1_wins")) | models.Q(player_2=player, player_1_wins__gt=models.F("player_2_wins")),
                                      distinct=True),
            wins=models.Sum(models.Case(models.When(player_1=player, then='player_1_wins'),
                                        models.When(player_2=player, then='player_2_wins'))),
            losses=models.Sum(models.Case(models.When(player_1=player, then='player_2_wins'),
                                          models.When(player_2=player, then='player_1_wins')))
        )

        for key in ["wins", "losses"]:  # if querysets are empty, sum will return None. We want 0 instead.
            aggregate[key] = 0 if aggregate[key] is None else aggregate[key]

        performance = Performance(player, **aggregate)
        bisect.insort_right(player_standings, performance)

    return list(reversed(player_standings))  # we sorted from low -> high but want to show high -> low


def penalty(rank_1: float, rank_2: float) -> float:
    # negative weight to create min matching.
    return -((rank_1 ** 2 - rank_2 ** 2) ** 2)


def ranking(duels, players, draw=False, **kwargs) -> typing.Tuple[typing.Dict[Player, float], typing.ByteString]:
    player_mapping = {
        player.name: player for player in players
    }

    freewin = Player.FREEWIN()
    all_players = set(players) - {freewin}  # don't count free wins
    win_graph = networkx.DiGraph()
    win_graph.add_nodes_from(all_players)

    duels = duels.filter(  # only duels that contain any wins make sense for ranking
        models.Q(player_1_wins__gt=0) | models.Q(player_2_wins__gt=0)
    ).values("player_1", "player_1_wins", "player_2", "player_2_wins")

    winning_map = {
        player: collections.defaultdict(int) for player in players
    }

    for duel in duels:
        player_1 = player_mapping[duel["player_1"]]
        player_2 = player_mapping[duel["player_2"]]
        winning_map[player_1][player_2] += duel["player_1_wins"]
        winning_map[player_2][player_1] += duel["player_2_wins"]

    for player, wins_against in winning_map.items():
        win_graph.add_weighted_edges_from((opponent, player, wins_against[opponent]) for opponent in wins_against)

    pageranking = {p: v * 100 for p, v in networkx.pagerank_numpy(win_graph, **kwargs).items()}

    if draw and win_graph:
        import io
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib import colors

        plt.figure(figsize=(16, 9))

        pos = networkx.shell_layout(win_graph)
        networkx.draw_networkx_nodes(win_graph, pos, node_size=700)
        max_wins = max(d["weight"] for (u, v, d) in win_graph.edges(data=True))
        color_values = [
            colors.to_hex(
                colors.hsv_to_rgb((ratio * 0.8 + 0.1, 0.9, (ratio + 1) / 2))
            )
            for ratio in map(lambda w: w / max_wins, range(1, max_wins + 1))
        ]
        legend = []

        winner_edges = [(v, u, d) for (u, v, d) in win_graph.edges(data=True) if
                        d["weight"] > win_graph[v][u]["weight"]]
        loser_edges = [(v, u, d) for (u, v, d) in win_graph.edges(data=True) if
                       d["weight"] <= win_graph[v][u]["weight"]]

        # we want to overlay bigger wins with smaller ones
        for wins, color in reversed(list(enumerate(color_values, start=1))):
            # we switch directions of edges so they show to winning against.
            # pagerank wants the direction towards the winner to show "significance"
            w_edges = [(v, u) for (u, v, d) in winner_edges if d["weight"] == wins]
            networkx.draw_networkx_edges(win_graph, pos, edgelist=w_edges, width=5, edge_color=color, arrowstyle="-|>")
            l_edges = [(v, u) for (u, v, d) in loser_edges if d["weight"] == wins]
            networkx.draw_networkx_edges(win_graph, pos, edgelist=l_edges, width=2, edge_color=color, arrowstyle="-|>")

            legend.append(Line2D([0], [0], marker='o', color='w', label=f'{wins}', markerfacecolor=color, markersize=6))

        networkx.draw_networkx_labels(win_graph, pos, font_size=10)

        plt.legend(handles=legend)

        bytes_io = io.BytesIO()
        plt.savefig(bytes_io, format="png")
        bytes_io.seek(0)
        return pageranking, base64.b64encode(bytes_io.read())

    return pageranking, b""


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
        players = self.players.exclude(name=Player.FREEWIN())

        if not self.rounds.exists():
            return [Performance(player, 0, 0, 0, 0) for player in players]

        return standing(self.duels(), players=players)

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
        freewin = Player.FREEWIN()
        all_players = set(self.players.all()) - {freewin}  # don't count free wins

        player_ranking, _ = ranking(duels=Duel.without_freewins(), players=Player.without_freewin())

        graph = networkx.Graph()

        graph.add_weighted_edges_from(
            (player, opponent, penalty(player_ranking[player], player_ranking[opponent]))
            for player, opponent in itertools.combinations(all_players, r=2)
        )

        matching = networkx.algorithms.matching.max_weight_matching(graph, maxcardinality=True)
        next_round = Round.objects.create(tournament=self, number=1)

        not_matched_players = all_players
        for player_1, player_2 in matching:
            Duel.objects.create(round=next_round, player_1=player_1, player_2=player_2)
            not_matched_players.remove(player_1)
            not_matched_players.remove(player_2)

        if not_matched_players:
            assert len(not_matched_players) == 1, "Something went wrong when matching up"
            last_player = next(iter(not_matched_players))
            Duel.objects.create(round=next_round, player_1=last_player, player_2=freewin,
                                player_1_wins=settings.MATCH_WINS_NEEDED)

        return next_round

    @atomic
    def start_next_round(self) -> 'Round':
        """Creates and returns the objects for the next round."""
        all_players = set(self.players.all())
        possible_matchings = set(map(frozenset, itertools.combinations(all_players, r=2)))
        previous_duels = self.duels().distinct()
        previous_matchings = set(
            frozenset((duel.player_1, duel.player_2))
            for duel in previous_duels
        )

        personalization = {
            perf.player: float(perf) for perf in self.standing
        }
        player_ranking, _ = ranking(
            duels=Duel.without_freewins(previous_duels),
            players=all_players,
            personalization=personalization
        )

        freewin = Player.FREEWIN()
        player_ranking.setdefault(freewin, -10)

        graph = networkx.Graph()

        graph.add_weighted_edges_from([
            (player, opponent, penalty(player_ranking[player], player_ranking[opponent]))
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
            if freewin == player_1:
                player_1, player_2 = player_2, player_1
                player_1_wins = settings.MATCH_WINS_NEEDED
            elif freewin == player_2:
                player_1_wins = settings.MATCH_WINS_NEEDED
            else:
                player_1_wins = 0

            Duel.objects.create(player_1=player_1, player_2=player_2, round=next_round, player_1_wins=player_1_wins)

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

    @classmethod
    def without_freewins(cls, from_duels=None):
        if from_duels is None:
            from_duels = cls.objects

        freewin = Player.FREEWIN()
        return from_duels.exclude(
            models.Q(player_1=freewin) | models.Q(player_2=freewin)
        )

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
    def players(self):
        return [self.player_1, self.player_2]

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

    if instance.players.count() < 2:
        raise ValidationError('A tournament needs at least 2 players.')
    if instance.players.count() % 2:
        freewin = Player.FREEWIN()
        assert freewin is not None, "Player.FREEWIN not set!"
        if freewin in instance.players.all():
            raise ValidationError(f"Remove the {freewin} player.")

        instance.players.add(freewin)
        instance.save()
    if not instance.rounds.exists():
        instance.start_first_round()


@receiver(models.signals.post_save, sender=User)
def connect_user_and_player(sender, instance: User, created: bool, **kwargs):
    """
    Connects new User objects to existing player objects or creates these.

    Will check if only first name already exists,
    if so and already connected will create a new player with <first> <last>.


    sender and kwargs are not used.
    """
    if not created:
        return

    mtg_pairings_app = apps.get_app_config("mtg_pairings")
    instance.groups.add(Group.objects.get(name=mtg_pairings_app.DEFAULT_GROUP_NAME))

    names = [
        instance.first_name,
        instance.last_name,
        f"{instance.first_name} {instance.last_name}",
        instance.username
    ]
    names = [n.strip() for n in names if n.strip()]

    for name in names:
        player, player_created = Player.objects.get_or_create(name=name)
        if player_created or player.user is None:
            player.user = instance
            player.save()
            break
    else:
        raise IntegrityError(f"No player object could be connected to user {instance.username}", instance)


