import pytest

from yebot.runtime.forwarding import build_forward_scene


def test_forward_scene_labels_every_node_and_reuses_target_nickname() -> None:
    nodes = build_forward_scene(
        [
            {"speaker": "target", "content": "怎么又轮到我了"},
            {"speaker": "群友甲", "content": "因为你最会整活"},
            {"speaker": "target", "content": "那我先撤退"},
        ],
        target_nickname="小李",
    )

    assert nodes[0].nickname == "小李（虚构）"
    assert nodes[1].nickname == "群友甲（虚构）"
    assert nodes[2].nickname == "小李（虚构）"
    assert [node.content for node in nodes] == [
        "怎么又轮到我了",
        "因为你最会整活",
        "那我先撤退",
    ]


@pytest.mark.parametrize(
    "nodes",
    (
        [
            {"speaker": "群友甲", "content": "第一条"},
            {"speaker": "群友乙", "content": "第二条"},
            {"speaker": "群友丙", "content": "第三条"},
        ],
        [
            {"speaker": "target", "content": "第一条"},
            {"speaker": "群友甲", "content": "第二条"},
        ],
        [
            {"speaker": "target", "content": "[CQ:at,qq=1]"},
            {"speaker": "群友甲", "content": "第二条"},
            {"speaker": "群友乙", "content": "第三条"},
        ],
    ),
)
def test_forward_scene_rejects_invalid_or_unsafe_nodes(nodes: object) -> None:
    with pytest.raises(ValueError):
        build_forward_scene(nodes, target_nickname="小李")
