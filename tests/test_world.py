from vla_pet.contracts import ActionKind, PetAction
from vla_pet.world import PetWorld


def advance_until_event(world: PetWorld, limit: int = 200):
    for _ in range(limit):
        event = world.update(0.05)
        if event:
            return event
    raise AssertionError("Action did not complete")


def test_walk_stays_inside_world() -> None:
    world = PetWorld()
    world.x = world.WIDTH - world.PET_WIDTH - 2
    world.apply_action(PetAction(ActionKind.WALK, direction=1, speed=220, duration=1, source="test"))
    event = advance_until_event(world)

    assert world.x == world.WIDTH - world.PET_WIDTH
    assert event.executed is ActionKind.WALK


def test_jump_uses_physics_and_lands() -> None:
    world = PetWorld()
    world.apply_action(PetAction(ActionKind.JUMP, speed=160, duration=0.3, source="test"))
    event = advance_until_event(world)

    assert event.executed is ActionKind.JUMP
    assert world.on_ground
    assert world.y == world.FLOOR_Y - world.PET_HEIGHT


def test_out_of_range_throw_becomes_safe_idle() -> None:
    world = PetWorld()
    world.toy.x = world.WIDTH - 30
    world.x = 10
    world.apply_action(PetAction(ActionKind.THROW, duration=0.3, source="test"))
    event = advance_until_event(world)

    assert event.requested is ActionKind.THROW
    assert event.executed is ActionKind.IDLE
    assert "could not" in event.result


def test_overlay_world_reverses_at_screen_edge() -> None:
    world = PetWorld(width=800, height=600, floor_y=592, bounce_edges=True)
    world.x = world.WIDTH - world.PET_WIDTH - 1
    world.apply_action(PetAction(ActionKind.WALK, direction=1, speed=180, duration=1, source="test"))
    world.update(0.05)

    assert world.x == world.WIDTH - world.PET_WIDTH
    assert world.vx < 0
    assert world.facing == -1
