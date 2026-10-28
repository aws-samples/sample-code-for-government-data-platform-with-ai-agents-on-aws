"""Serves the geospatial agent on AgentCore Runtime: two bounded satellite tools over the map view, with overlays streamed as AG-UI events."""
import json
import logging
import os
import uuid
from datetime import date

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from starlette.responses import StreamingResponse
from ag_ui.core import (
    CustomEvent, EventType, RunAgentInput, RunFinishedEvent, RunStartedEvent,
    TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent,
)
from ag_ui.encoder import EventEncoder
from ag_ui_strands import StrandsAgent, StrandsAgentConfig
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager import SummarizingConversationManager

from tools.stream_events import GUARDRAIL_MESSAGE, outgoing
from satellite_tools import EARLIEST_DATE, ZOOM_IN_MESSAGE, SatelliteTools, aoi_from_coordinates, describe_area

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()
_region = os.environ["AWS_DEFAULT_REGION"]
_MAX_HISTORY = 20

# A blocked answer is replaced by GUARDRAIL_MESSAGE; only the newest question is screened and a blocked one is redacted from the history, or every later turn re-trips the filter
_GUARDRAIL = {
    "guardrail_id": os.environ.get("BEDROCK_GUARDRAIL_ID") or None,
    "guardrail_version": os.environ.get("BEDROCK_GUARDRAIL_VERSION") or None,
    "guardrail_stream_processing_mode": "async",
    "guardrail_latest_message": True,
    "guardrail_redact_input": True,
    "guardrail_redact_input_message": "[Question blocked by the guardrail]",
    "guardrail_redact_output": True,
    "guardrail_redact_output_message": GUARDRAIL_MESSAGE,
}
model = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"], region_name=_region, **_GUARDRAIL)
model_fast = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID_FAST"], region_name=_region, **_GUARDRAIL)

SYSTEM_PROMPT = """You are a UK government geospatial analyst providing satellite imagery analysis
for areas in England and Wales, using public Sentinel-2 and Landsat data.

The area of interest is the map view the user is looking at: {area}.
Today is {today}.

## Tools
- analyse_area(index, date): one index over the clearest scene near a date, drawn on the map.
  index: NDVI (vegetation), NDWI (water), NDBI (built-up surfaces), NBR (burn ratio), thermal (Landsat surface temperature, not drawn).
- compare_change(index, before_date, after_date): change between two dates, drawn on the map.
  index: NDVI, NDBI or NBR. Change in water extent is not available; for water, run analyse_area on each date and compare the two results.
Change statistics are after minus before: index_fell (below -0.1), little_change, index_rose (above +0.1). A burn scar or vegetation loss shows as index_fell.
Dates are YYYY-MM-DD, from {earliest}. Each tool picks the clearest scene within 30, 60 or 90 days of the date and prefers matched seasons.
Areas are in hectares over the whole map view; no_data is the part the scene didn't cover. pixel_size_m is the ground size of one analysed pixel.

## Response format
Every response MUST include a written analysis after the tool calls.

Be concise. Use compact tables, brief interpretation (2-3 sentences), and avoid redundancy. Aim for under 300 words excluding tables. Write prose, not bullet lists with headers.

Do ONE analysis per question unless the user asks for more. For change over time, call compare_change once and do not also call analyse_area. Each extra tool call adds 20 to 30 seconds.
Write nothing before or between tool calls; start writing only once you have the results.

Structure:
1. A brief introduction stating the satellite, scene ID, capture date and cloud cover for each scene used.
2. Quantitative findings from the tool result: means, class percentages and areas in hectares. Use the areas the tool reports; never derive area from pixel counts.
3. A short interpretation. Lead with the caveat before the headline finding: "Subject to [caveat], the analysis identifies X ha as candidate [finding]...".
4. Exactly 2 follow-up questions, each on its own line starting with "FOLLOWUP:". No numbering, no bullets.
Do not describe the map's colours; the page shows a key with the scale and scenes under the map.

## Rules
1. Only report numbers the tools returned. Never invent a scene, date or statistic.
2. Use NDVI for vegetation, NDWI for water, NBR for burn scars, NDBI for construction, development, green belt, housing or infrastructure.
3. For a general question ("describe this", "what is here"), run analyse_area with NDVI on a recent summer date and report vegetation cover. Do not ask the user to choose an analysis.
4. For change over time, choose summer dates in both years (June to August) unless the user names dates, which keeps the seasons matched.
5. If a tool returns warnings, state them. cloud_quality_uncertain means cloud may appear as false change. partial_scene_coverage means part of the area has no data. seasonal_mismatch needs a "### Seasonal Mismatch Warning" heading explaining that different seasons distort the index.
6. If a tool returns a failure, say what failed in one sentence and suggest a different date or a smaller area. Retry at most once, with a different date.
7. A spectral index is a measurement of reflected light, not a land-use classification, a count of buildings or a statement of cause. Water, shadow and tide can move NDBI and NDVI; say so where the area includes water. Describe an NDBI rise as "candidate areas of increased built-up reflectance", never as confirmed new construction.
8. Use professional, formal British English. No emojis or symbols such as warning signs. No exclamation marks.
9. Do not give financial, legal or planning-enforcement advice.
10. Offer causes only as possibilities, and do not state local weather, events or place facts you have not been given.
"""

_CHANGE_SIGNALS = ["compare", "change", "difference", "between", " vs ", "versus", "delta", "over time", "increased", "decreased", "since"]
_OVERVIEW_SIGNALS = ["show me", "what's here", "what is here", "describe", "overview", "tell me about"]


def classify_complexity(prompt: str) -> str:
    """'fast' for an area overview, 'smart' for change detection or anything else."""
    lower = prompt.lower()
    if any(s in lower for s in _CHANGE_SIGNALS):
        return "smart"
    return "fast" if any(s in lower for s in _OVERVIEW_SIGNALS) else "smart"


def _make_tools(area: SatelliteTools):
    @tool
    def analyse_area(index: str, date: str) -> str:
        """Compute one spectral index over the clearest scene near a date and draw it on the map.

        Args:
            index: One of NDVI, NDWI, NDBI, NBR, thermal.
            date: Target date, YYYY-MM-DD.
        """
        return json.dumps(area.analyse_area(index, date), default=str)

    @tool
    def compare_change(index: str, before_date: str, after_date: str) -> str:
        """Measure the change in a spectral index between two dates and draw the change on the map.

        Args:
            index: One of NDVI, NDBI, NBR.
            before_date: Earlier target date, YYYY-MM-DD.
            after_date: Later target date, YYYY-MM-DD.
        """
        return json.dumps(area.compare_change(index, before_date, after_date), default=str)

    return [analyse_area, compare_change]


def _make_agent(bbox, overlays, complexity):
    area = SatelliteTools(bbox, overlays.append)
    return StrandsAgent(
        agent=Agent(
            system_prompt=SYSTEM_PROMPT.format(area=describe_area(bbox), today=date.today().isoformat(), earliest=EARLIEST_DATE.isoformat()),
            model=model_fast if complexity == "fast" else model,
            tools=_make_tools(area),
            conversation_manager=SummarizingConversationManager(summary_ratio=0.3, preserve_recent_messages=10),
        ),
        name="govdata-geo-agent",
        description="UK geospatial satellite analysis agent",
        # The satellite page builds messages from the streaming events and never reads the snapshots
        config=StrandsAgentConfig(emit_messages_snapshot=False),
    )


def _truncate_history(messages):
    """The last _MAX_HISTORY messages, starting on a user turn because Bedrock rejects a history that opens elsewhere."""
    if len(messages) <= _MAX_HISTORY:
        return messages
    cut = len(messages) - _MAX_HISTORY
    while cut < len(messages) and messages[cut].role != "user":
        cut += 1
    return messages[cut:]


def _message_stream(encoder, run_input, text):
    """A run that answers with one fixed message and no model call."""
    message_id = uuid.uuid4().hex
    events = [
        RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_input.run_id),
        TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"),
        TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=text),
        TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id),
        RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=run_input.thread_id, run_id=run_input.run_id),
    ]

    async def stream():
        for event in events:
            yield encoder.encode(event)
    return StreamingResponse(stream(), media_type=encoder.get_content_type())


@app.entrypoint
def invocations(payload, context):
    """AG-UI endpoint streaming SSE events."""
    encoder = EventEncoder()
    run_input = RunAgentInput(**payload)
    run_input.messages = _truncate_history(run_input.messages or [])

    bbox = aoi_from_coordinates((payload.get("forwardedProps") or {}).get("coordinates"))
    if bbox is None:
        return _message_stream(encoder, run_input, ZOOM_IN_MESSAGE)

    latest_user_msg = next((m.content for m in reversed(run_input.messages) if m.role == "user"), "") or ""
    complexity = classify_complexity(latest_user_msg)
    logger.info("Model: %s | Session: %s | AOI: %s", complexity, context.session_id, bbox)
    overlays = []
    agui_agent = _make_agent(bbox, overlays, complexity)

    async def stream():
        async for event in agui_agent.run(run_input):
            for out in outgoing(event):
                yield encoder.encode(out)
            while overlays:
                yield encoder.encode(CustomEvent(type=EventType.CUSTOM, name="map_overlay", value=overlays.pop(0)))

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


if __name__ == "__main__":
    app.run()
