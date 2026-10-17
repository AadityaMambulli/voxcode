import pytest

from voxcode.stt import _remove_repeated_text


@pytest.mark.fake
def test_remove_repeated_phrase() -> None:
    assert (
        _remove_repeated_text("hello can you hear me hello can you hear me")
        == "hello can you hear me"
    )
