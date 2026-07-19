import numpy as np
import pytest

from vla_pet.contracts import ActionIntent, ActionKind, ChatRequest, VisualQuestion
from vla_pet.notifications import decode_dbus_string, notification_from_strings
from vla_pet.overlay import decision_request_ready
from vla_pet.policy import (
    SmolLMPetLanguage,
    chat_fallback,
    chat_reply_is_degenerate,
    chat_reply_repeats_history,
    clean_answer,
    clean_dialogue,
    infer_confirmed_action_intent,
    narration_is_grounded,
    resolve_quantization_mode,
)
from vla_pet.world import PetWorld


def test_visual_question_validates_user_capture() -> None:
    request = VisualQuestion(
        image=np.zeros((360, 640, 3), dtype=np.uint8),
        question="What is visible?",
        notification_context="App: Mail. Title: New message",
    )
    request.validate()

    with pytest.raises(ValueError):
        VisualQuestion(np.zeros((3, 256, 256), dtype=np.float32), "What?").validate()


def test_screen_answer_is_cleaned_and_bounded() -> None:
    assert clean_answer(" Assistant:  A browser is open. \n") == "A browser is open."
    answer = clean_answer("word " * 100)
    assert len(answer) <= 240
    assert answer.endswith("…")


def test_notification_monitor_parser() -> None:
    assert decode_dbus_string('   string "Mail\\nClient"') == "Mail\nClient"
    notification = notification_from_strings(["Mail", "mail-icon", "New message", "Hello there"])
    assert notification is not None
    assert notification.context == "App: Mail. Title: New message. Message: Hello there"


def test_user_can_interrupt_and_reposition_pet() -> None:
    world = PetWorld(width=500)
    old_sequence = world.sequence_id
    world.interrupt()
    world.move_horizontal(9999)
    assert world.sequence_id == old_sequence + 1
    assert world.x == world.WIDTH - world.PET_WIDTH
    assert not world.is_busy


def test_pick_up_drop_uses_slow_gravity_then_lands() -> None:
    world = PetWorld(height=600, floor_y=580)
    world.pick_up()
    world.move_to(120, 80)
    world.drop()

    world.update(0.1)
    assert world.user_falling
    assert world.y == pytest.approx(82.6)
    assert world.vy == pytest.approx(26.0)

    for _ in range(100):
        world.update(0.1)
    assert world.on_ground
    assert not world.user_falling
    assert world.y == world.FLOOR_Y - world.PET_HEIGHT


def test_chat_request_and_sanitizer() -> None:
    request = ChatRequest("Hello pet!", (("user", "Hi"), ("pet", "Hello!")))
    request.validate()
    assert clean_dialogue("Pet: I am happy. How are you?") == "I am happy. How are you?"
    assert clean_dialogue("Hello pet! I was walking.", repeated_text="Hello pet!") == "I was walking."
    assert len(clean_dialogue("word " * 200)) <= 320
    assert clean_dialogue("I am walking. I am walking! I am walking.") == "I am walking."
    assert narration_is_grounded("I jumped so high!", ActionKind.JUMP)
    assert not narration_is_grounded("The image shows a desktop game.", ActionKind.JUMP)
    broken = (
        "I'm a little girl, I'm a little princess, I'm not a princess, "
        "I've got a lot of princesses, but I'm not a princess."
    )
    assert chat_reply_is_degenerate(broken)
    assert not chat_reply_is_degenerate("That sounds fun—let's do it!")
    assert "computer" in chat_fallback("Tell me a joke").lower()
    history = (("user", "Can you jump?"), ("pet", "I can jump."))
    assert chat_reply_repeats_history("i can jump", history)
    assert not chat_reply_repeats_history("I can dance too!", history)
    assert "punchline" in SmolLMPetLanguage.chat_prompt("Tell me a joke")
    assert "jump" in SmolLMPetLanguage.chat_prompt("Can you jump?")


def test_smolllm_reply_must_confirm_a_direct_action_command() -> None:
    assert (
        infer_confirmed_action_intent("Can you jump?", "I'm ready to jump!")
        is ActionIntent.JUMP
    )
    assert infer_confirmed_action_intent("Can you jumping?", "I'll jump happily!") is ActionIntent.JUMP
    assert infer_confirmed_action_intent("Jump!", "Let's hop!") is ActionIntent.JUMP
    assert infer_confirmed_action_intent("Walk to the left", "I'll go left!") is ActionIntent.WALK_LEFT
    assert infer_confirmed_action_intent("What is jumping?", "Jumping is fun.") is None
    assert infer_confirmed_action_intent("Can you jump?", "I'd rather rest.") is None


def test_cpu_quantization_auto_resolution() -> None:
    assert resolve_quantization_mode("auto", "cpu") == "int8"
    assert resolve_quantization_mode("none", "cpu") == "none"
    assert resolve_quantization_mode("auto", "cuda") == "none"
    with pytest.raises(ValueError):
        resolve_quantization_mode("int8", "cuda")


def test_chat_and_narration_do_not_pause_locomotion_decisions() -> None:
    common = {
        "world_busy": False,
        "on_ground": True,
        "dragging": False,
        "now": 10.0,
        "next_decision_at": 9.0,
    }
    assert decision_request_ready(**common, pending_kinds=("chat", "narrate"))
    assert not decision_request_ready(**common, pending_kinds=("chat", "decide"))
