"""Turns a tool result that carries inline visuals into ordered AG-UI events: a section event for each run of text,
a chart or map event for each visual, in the order the tool wrote them. The frontend renders them in that order."""
import json

from ag_ui.core import CustomEvent

_decoder = json.JSONDecoder()
_MARKERS = {"__chart__": "chart", "__map__": "map"}


def _unquote(content: str) -> str:
    if content.startswith('"') and content.endswith('"'):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            pass
    return content


def split_result(content: str):
    """(remaining text, events). The text is the result with every visual removed, for the model's context."""
    content = _unquote(content or "")
    events, text_parts, cursor = [], [], 0
    while True:
        starts = [(content.find(f'{{"{m}"', cursor), m) for m in _MARKERS]
        starts = [(i, m) for i, m in starts if i != -1]
        if not starts:
            break
        start, marker = min(starts)
        try:
            data, end = _decoder.raw_decode(content, start)
        except json.JSONDecodeError:
            break
        text = content[cursor:start].strip()
        if text:
            events.append(CustomEvent(name="section", value=text))
            text_parts.append(text)
        if data.get(marker) and data.get("config"):
            events.append(CustomEvent(name=_MARKERS[marker], value=data["config"]))
        cursor = end
    tail = content[cursor:].strip()
    if tail and events:
        events.append(CustomEvent(name="section", value=tail))
    if tail:
        text_parts.append(tail)
    return "\n".join(text_parts), events


def has_visuals(events) -> bool:
    return any(e.name in ("chart", "map") for e in events)
