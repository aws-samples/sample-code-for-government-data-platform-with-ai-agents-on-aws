"""Serves the guided walkthrough agent on AgentCore Runtime, streaming AG-UI events with charts and maps as custom events."""
import logging
import os
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from starlette.responses import StreamingResponse
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_strands import StrandsAgent, StrandsAgentConfig
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager import SummarizingConversationManager

from tools.sections import split_result, has_visuals
from tools.stream_events import outgoing
from tools.run_sql import run_sql, set_query_id
from tools.describe_schema import describe_schema
from tools.create_chart import create_chart
from tools.create_map import create_map
from tools.create_choropleth import create_choropleth
from tools.summarise_area import summarise_area
from tools.get_uk_facts import get_uk_facts
from platform_facts import get_platform_facts
from walkthrough_prompt import make_walkthrough_prompt

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()
_MAX_HISTORY = 20

# No guardrail: the scripted prompts ("briefing a minister", "Continue") trip the denied-topic filter
model = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"], region_name=os.environ["AWS_DEFAULT_REGION"])

TOOLS = [get_platform_facts, run_sql, describe_schema, create_chart, create_map, create_choropleth, summarise_area, get_uk_facts]

_agent = StrandsAgent(
    agent=Agent(
        system_prompt=make_walkthrough_prompt(),
        model=model,
        tools=TOOLS,
        conversation_manager=SummarizingConversationManager(summary_ratio=0.3, preserve_recent_messages=10),
    ),
    name="govdata-walkthrough-agent",
    description="Guided walkthrough demo agent",
    # The walkthrough page builds messages from the streaming events and never reads the snapshots
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


@app.entrypoint
def invocations(payload, context):
    """AG-UI endpoint streaming SSE events."""
    encoder = EventEncoder()
    run_input = RunAgentInput(**payload)
    run_input.messages = _truncate_history(run_input.messages or [])
    set_query_id(payload.get("runId") or str(uuid.uuid4()))
    logger.info("Session: %s", context.session_id)

    async def stream():
        async for event in _agent.run(run_input):
            if getattr(event, "type", None) == "TOOL_CALL_RESULT":
                # A result with visuals is shown as it is: text and visuals in the tool's order, the model sees the text only
                cleaned, parts = split_result(getattr(event, "content", "") or "")
                if has_visuals(parts):
                    event.content = cleaned
                    yield encoder.encode(event)
                    for part in parts:
                        yield encoder.encode(part)
                    continue
            for out in outgoing(event):
                yield encoder.encode(out)

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


if __name__ == "__main__":
    app.run()
