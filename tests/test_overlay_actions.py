from vla_pet.contracts import ActionKind, PetAction
from vla_pet.overlay_actions import OverlayActionScheduler, sprite_needs_flip
from vla_pet.world import PetWorld


def proposed(raw: tuple[float, ...]) -> PetAction:
    return PetAction(
        ActionKind.WALK,
        direction=-1 if raw[0] < 0 else 1,
        speed=140,
        duration=1,
        source="test",
        raw_vector=raw,
    )


def test_walking_sprite_native_direction_is_right() -> None:
    assert not sprite_needs_flip(ActionKind.WALK, 1)
    assert sprite_needs_flip(ActionKind.WALK, -1)


def test_high_jump_channel_triggers_jump_then_cooldown_walk() -> None:
    scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)
    prediction = proposed((0.3, 1.3, 0.2, 0.0, 0.0, 0.0))

    assert scheduler.choose(prediction, world, 100).kind is ActionKind.JUMP
    assert scheduler.choose(prediction, world, 102).kind is ActionKind.WALK


def test_throw_requires_screen_center_and_interaction_score() -> None:
    scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)
    world.x = world.WIDTH / 2 - world.PET_WIDTH / 2
    prediction = proposed((0.3, 0.2, 1.3, 0.0, 0.0, 0.0))

    assert scheduler.choose(prediction, world, 100).kind is ActionKind.THROW


def test_emotion_and_edge_conditions_trigger_poses() -> None:
    sad_scheduler = OverlayActionScheduler()
    edge_scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)

    sad = sad_scheduler.choose(proposed((0.3, 0.2, 0.2, -0.8, 0.0, 0.0)), world, 100)
    happy = edge_scheduler.choose(
        proposed((0.3, 0.2, 0.2, 0.0, 0.0, 0.0)),
        world,
        100,
        edge_bounced=True,
    )
    assert sad.kind is ActionKind.SAD
    assert happy.kind is ActionKind.HAPPY


def test_direction_deadzone_keeps_current_facing() -> None:
    scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)
    world.facing = -1
    action = scheduler.choose(proposed((0.02, 0.0, 0.0, 0.0, 0.0, 0.0)), world, 100)
    assert action.direction == -1


def test_discrete_vlm_special_action_is_respected_with_cooldown() -> None:
    scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)
    vlm_jump = PetAction(ActionKind.JUMP, direction=1, duration=1, source="vlm", note="JUMP")

    assert scheduler.choose(vlm_jump, world, 100).kind is ActionKind.JUMP
    assert scheduler.choose(vlm_jump, world, 102).kind is ActionKind.WALK


def test_idle_routine_keeps_its_requested_pause_duration() -> None:
    scheduler = OverlayActionScheduler()
    world = PetWorld(width=1000, height=700, floor_y=692, bounce_edges=True)
    pause = PetAction(ActionKind.IDLE, duration=2.4, source="life")
    chosen = scheduler.choose(pause, world, 100)
    assert chosen.kind is ActionKind.IDLE
    assert chosen.duration == 2.4
