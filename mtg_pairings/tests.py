from hypothesis import given, strategies, reproduce_failure

# Create your tests here.
from . import models


def performances(**kwargs):
    parameters = dict(player=strategies.builds(models.Player, name=strategies.text()),
                      match_wins=strategies.integers(min_value=0), wins=strategies.integers(min_value=0),
                      match_losses=strategies.integers(min_value=0), losses=strategies.integers(min_value=0))
    parameters.update(kwargs)
    return strategies.builds(models.Performance, **parameters)


@reproduce_failure('4.9.0', b'AXicY2BAAUwIJgAAMAAD')
@given(performances(), performances())
def test_penalty(player_1: models.Performance, player_2: models.Performance):
    penalty: float = models.penalty(player_1, player_2)
    if player_1 == player_2:
        assert penalty == 0
    else:
        assert penalty < 0


@given(performances(), performances())
def test_performance_add(performance_1: models.Performance, performance_2: models.Performance):
    performance_2.player = performance_1.player  # more effective than filtering
    a = performance_1 + performance_2
    assert a.match_wins == performance_1.match_wins + performance_2.match_wins
    assert a.match_losses == performance_1.match_losses + performance_2.match_losses
    assert a.wins == performance_1.wins + performance_2.wins
    assert a.losses == performance_1.losses + performance_2.losses

