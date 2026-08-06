"""Prompt contract for explicit response-medium requests."""

from __future__ import annotations

from .models import ResponseMode


def build_response_media_guidance(mode: ResponseMode) -> str:
    """Tell the model that YeBot will deliver the selected medium after generation."""

    if mode is ResponseMode.TEXT:
        return ""
    return (
        "当前回复媒介已经由 YeBot 选定，并且该媒介发送能力可用。程序会在你生成文本后，"
        "自动把文本转换成选定的语音并发送给用户；你不需要调用工具，也不要判断平台是否支持语音。"
        "只生成用户真正需要的正常内容，不要输出“语音模式”、“我无法发送语音”、"
        "“发不了语音”、“不能发送语音”或任何媒体控制说明。"
        "如果用户只是在要求你改用语音回复，没有提出其他问题，就直接简短确认，"
        "例如“好的，我用语音回复你。”；不要把这个请求回答成能力限制或拒绝。"
    )
