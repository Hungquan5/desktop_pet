from vla_pet.contracts import ActionEvent, ActionKind
from vla_pet.narration import sanitize_narration, template_narration


def make_event(result: str = "jumped and landed safely") -> ActionEvent:
    return ActionEvent(
        sequence_id=1,
        requested=ActionKind.JUMP,
        executed=ActionKind.JUMP,
        result=result,
        nearby_object="toy",
        elapsed=1.2,
        source="test",
    )


def test_sanitizes_to_one_short_sentence() -> None:
    text = "  I made a very exciting jump over my favorite little blue toy today! Another sentence. "
    result = sanitize_narration(text)

    assert len(result.split()) <= 12
    assert "Another" not in result
    assert result.endswith((".", "!", "?"))


def test_template_describes_failure_without_claiming_success() -> None:
    event = make_event("could not reach the toy")
    assert "tried" in template_narration(event).lower()
