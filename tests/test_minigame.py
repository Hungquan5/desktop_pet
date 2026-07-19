from vla_pet.minigame import ReactionGame


def test_reaction_game_is_bounded_deterministic_and_non_punishing() -> None:
    first = ReactionGame(rounds=10, seed=7)
    second = ReactionGame(rounds=10, seed=7)
    assert first.start() == second.start()
    targets: list[int] = []
    for _ in range(10):
        targets.append(first.target)
        first.choose(first.target)
        second.choose(second.target)
    assert first.complete and second.complete
    assert first.score == 10 and second.score == 10
    assert all(0 <= target < 9 for target in targets)
    assert not first.choose(0) and first.score == 10
