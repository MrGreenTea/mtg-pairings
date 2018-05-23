import os

from hypothesis import given, strategies, assume, settings
from hypothesis.extra.django import TestCase

# Create your tests here.
from . import models


def performances(**kwargs):
    parameters = dict(player=strategies.builds(models.Player, name=strategies.text()),
                      match_wins=strategies.integers(min_value=0), wins=strategies.integers(min_value=0),
                      match_losses=strategies.integers(min_value=0), losses=strategies.integers(min_value=0))
    parameters.update(kwargs)
    return strategies.builds(models.Performance, **parameters)


class TestModels(TestCase):
    @settings(use_coverage=int(os.environ.get('HYPOTHESIS_USE_COVERAGE', 1)))
    @given(performances(), performances(), strategies.integers(min_value=1))
    def test_penalty(self, player_1: models.Performance, player_2: models.Performance,
                     delta: int):
        assume(player_1 > player_2)

        player_3 = player_1 + models.Performance(player_1.player, delta, 0, 0, 0)
        player_4 = player_2 + models.Performance(player_2.player, delta, 0, 0, 0)

        assert models.penalty(player_3, player_4) > models.penalty(player_1, player_2)


@given(performances(), performances())
def test_performance_add(performance_1: models.Performance, performance_2: models.Performance):
    performance_2.player = performance_1.player  # more effective than filtering
    a = performance_1 + performance_2
    assert a.match_wins == performance_1.match_wins + performance_2.match_wins
    assert a.match_losses == performance_1.match_losses + performance_2.match_losses
    assert a.wins == performance_1.wins + performance_2.wins
    assert a.losses == performance_1.losses + performance_2.losses

