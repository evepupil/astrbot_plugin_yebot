from types import SimpleNamespace

from yebot.runtime.addressing import is_reply_prefixed_wake


class Reply:
    type = "Reply"

    def __init__(self, message_str: str = "") -> None:
        self.message_str = message_str


def plain(text: str) -> object:
    return SimpleNamespace(type="Plain", text=text)


def test_reply_prefix_uses_current_text_after_reply() -> None:
    assert is_reply_prefixed_wake(
        [Reply("引用内容里也有叶桐"), plain("叶桐 查一下")],
        ["叶桐"],
    )


def test_reply_prefix_does_not_match_only_quoted_text() -> None:
    assert not is_reply_prefixed_wake([Reply("叶桐 查一下")], ["叶桐"])


def test_reply_prefix_supports_configured_prefixes_and_non_text_segments() -> None:
    assert is_reply_prefixed_wake(
        [Reply(), plain("/ 查一下")],
        ["叶桐", "/"],
    )
    assert not is_reply_prefixed_wake(
        [Reply(), SimpleNamespace(type="Image"), plain("查一下")],
        ["叶桐"],
    )
