import math

import pytest

from vla_pet.contracts import ActionKind
from vla_pet.policy import SmolVLMPetPolicy, map_action_vector


def test_maps_strongest_dimension_and_motion_parameters() -> None:
    action = map_action_vector([-0.9, 0.2, 0.1, 0.3, 1.0, -1.0])

    assert action.kind is ActionKind.WALK
    assert action.direction == -1
    assert action.speed == 200.0
    assert action.duration == 0.5


@pytest.mark.parametrize(
    ("vector", "expected"),
    [
        ([0.1, 0.8, 0.0, 0.1, 0, 0], ActionKind.JUMP),
        ([0.1, 0.0, 0.8, 0.1, 0, 0], ActionKind.THROW),
        ([0.1, 0.0, 0.0, 0.8, 0, 0], ActionKind.HAPPY),
        ([0.1, 0.0, 0.0, -0.8, 0, 0], ActionKind.SAD),
        ([0.1, 0.1, 0.1, 0.1, 0, 0], ActionKind.IDLE),
    ],
)
def test_maps_action_families(vector: list[float], expected: ActionKind) -> None:
    assert map_action_vector(vector).kind is expected


def test_rejects_bad_vectors() -> None:
    with pytest.raises(ValueError, match="six"):
        map_action_vector([0, 1])
    with pytest.raises(ValueError, match="non-finite"):
        map_action_vector([0, 0, 0, math.nan, 0, 0])


def test_overlay_mode_is_locomotion_only() -> None:
    action = map_action_vector([0.01, 1.0, 1.0, -1.0, 0.0, 0.0], mode="overlay")
    assert action.kind is ActionKind.WALK
    assert action.direction == 1


def test_smolvlm_discrete_action_parser() -> None:
    assert SmolVLMPetPolicy.parse_action("WALK_LEFT", x=0, vx=0)[:2] == (ActionKind.WALK, -1)
    assert SmolVLMPetPolicy.parse_action("I choose: JUMP", x=0, vx=0)[0] is ActionKind.JUMP
    assert SmolVLMPetPolicy.parse_action("invalid answer", x=0.8, vx=0)[:2] == (ActionKind.WALK, -1)
