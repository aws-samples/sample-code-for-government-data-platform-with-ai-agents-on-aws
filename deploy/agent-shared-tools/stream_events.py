"""Trims the AG-UI stream the agents send to the browser and turns two stop conditions into plain messages."""
from ag_ui.core import CustomEvent, EventType

# RUN_ERROR text for Strands' MaxTokensReachedException, which the adapter forwards as is
TOKEN_LIMIT_ERROR = "maximum token limit"
TOKEN_LIMIT_MESSAGE = "That answer ran past the length limit and was cut off. Try a narrower question, for example one area or one year."
GUARDRAIL_MESSAGE = "Sorry, I can't help with that."


def _redaction(payload):
    """The assistant redaction message in a RAW Strands event, or None. Model chunks arrive wrapped as {"event": chunk}."""
    if not isinstance(payload, dict):
        return None
    redact = payload.get("redactContent") or (payload.get("event") or {}).get("redactContent") or {}
    return redact.get("redactAssistantContentMessage")


def outgoing(event):
    """The events to send for one adapter event: RAW dropped bar a guardrail redaction, sent as CUSTOM "guardrail", and the token-limit RUN_ERROR reworded."""
    kind = getattr(event, "type", None)
    if kind == EventType.RAW:
        message = _redaction(getattr(event, "event", None))
        return [CustomEvent(type=EventType.CUSTOM, name="guardrail", value={"message": message})] if message else []
    if kind == EventType.RUN_ERROR and TOKEN_LIMIT_ERROR in (getattr(event, "message", "") or ""):
        event.message = TOKEN_LIMIT_MESSAGE
    return [event]
