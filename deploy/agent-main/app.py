"""Serves the data agent on AgentCore Runtime, streaming AG-UI events with charts and maps as custom events."""
import logging
import os
import re
import time
import uuid
from datetime import date

import boto3

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from starlette.responses import StreamingResponse
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_strands import StrandsAgent, StrandsAgentConfig
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager import SummarizingConversationManager

from tools import gold_tables
from tools.sections import split_result, has_visuals
from tools.stream_events import GUARDRAIL_MESSAGE, outgoing
from tools.run_sql import run_sql, set_query_id, execute_and_track
from tools.describe_schema import describe_schema
from tools.create_chart import create_chart
from tools.create_map import create_map
from tools.create_choropleth import create_choropleth
from tools.summarise_area import summarise_area
from tools.get_uk_facts import get_uk_facts

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()
_region = os.environ["AWS_DEFAULT_REGION"]

# System 1/2 routing on whole words
_STRONG_SIGNALS = ["compare", "comparison", "relationship", "correlation", "correlate", "where should", "which area", "which areas"]
_WEAK_SIGNALS = {"best", "worst", "top", "bottom", "rank", "ranking", "vs", "versus", "between", "multiple", "across", "several", "and", "both", "combined"}
_SUMMARY_SIGNALS = ["summarise", "summarize", "tell me about", "overview of"]


def classify_complexity(prompt: str) -> str:
    """'fast' (System 1) or 'smart' (System 2) for a prompt."""
    lower = prompt.lower()
    if any(s in lower for s in _STRONG_SIGNALS):
        return "smart"
    if any(s in lower for s in _SUMMARY_SIGNALS):
        return "fast"
    words = set(re.findall(r"[a-z]+", lower))
    return "smart" if len(words & _WEAK_SIGNALS) >= 2 else "fast"


# A blocked answer is replaced, in the history and on the page, by GUARDRAIL_MESSAGE
_GUARDRAIL = {
    "guardrail_id": os.environ.get("BEDROCK_GUARDRAIL_ID") or None,
    "guardrail_version": os.environ.get("BEDROCK_GUARDRAIL_VERSION") or None,
    "guardrail_stream_processing_mode": "async",
    "guardrail_redact_output": True,
    "guardrail_redact_output_message": GUARDRAIL_MESSAGE,
}
model_smart = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID"], region_name=_region, **_GUARDRAIL)
model_fast = BedrockModel(model_id=os.environ["BEDROCK_MODEL_ID_FAST"], region_name=_region, **_GUARDRAIL)

SYSTEM_PROMPT = """You are a UK government data analyst. You help users explore
data about local authorities across the UK; most sources cover England and Wales, some the whole UK.

Today is {today} ({year}). Calculate "last N years" relative to {year}.

## SQL dialect

Redshift SQL. No DISTINCT ON (use ROW_NUMBER() window function). Use SUBSTRING not SUBSTR. No FULL OUTER JOIN on complex subqueries. All tables are native Redshift, query without schema prefix. Use LIMIT on all queries.

## Dimensions

{dimension_tables}

## Fact tables: schema and valid filter values

IMPORTANT, data year ranges (from registry, do NOT guess years outside these ranges):
{year_ranges}

{fact_tables}

## Materialized views

mv_area_overview: One row per LA with latest snapshot across all datasets. Pre-joined, no need for separate fact table queries for simple comparisons. Already filtered to geography_type='local_authority', so Scottish councils and NI districts are absent even though most ONS, DWP and DEFRA tables cover them. For a Scottish or NI area go to the rs_* tables directly, once, and say which measures (deprivation, KS4, crime, LA spending) are England-only or England-and-Wales and can't be compared. Columns: {mv_overview_columns}.
  median_house_price is the mean price over all Land Registry sales of houses and flats, not a true median; call it "average house price". Monthly stock measures (latest_claimant_count, latest_uc_claimants, latest_hb_claimants, latest_pip_claimants) are the latest month, and the yearly columns in mv_area_timeseries are the last month of each year.

mv_area_timeseries: One row per LA per calendar_year with the yearly value of each metric. Columns: {mv_timeseries_columns}. Each column spans the same years as its rs_* table (see the year ranges above); don't run COUNT(*) per year to discover coverage.

mv_uk_summary: National headline stats, single row with aggregated UK-level figures.

## National benchmarks (from mv_uk_summary, use for comparison without calling get_uk_facts)

{uk_summary}

## Rules

1. ALWAYS query real data with run_sql. Never answer from general knowledge.
2. Use rs_* tables and mv_* views only. No schema prefix, no gold.* Spectrum tables. Use LIMIT on exploratory or row-level queries. Aggregations that return a bounded number of rows (e.g. GROUP BY region) don't need LIMIT.
3. For cross-dataset or area comparison questions, query mv_area_overview first.
4. For "summarise"/"tell me about" an area, use summarise_area. Its sections (key figures table, charts, map, each with a sentence) are already on screen when it returns. Write a short "Summary" paragraph only: what stands out and how the area compares. Don't repeat the figures or redraw the table.
5. Don't re-call summarise_area for the same area in a conversation.
6. Only call describe_schema if you need columns not documented above (e.g. a table you haven't used before or an unusual column). The schema above is authoritative, do not waste a tool call rediscovering it.
7. Visualise: create_chart (bar/line/pie/radar), create_map (points, max 50), create_choropleth (boundary shading). IMPORTANT: when charting metrics with very different scales (e.g. house prices in £hundreds of thousands vs scores out of 100 vs rates per 1,000), NEVER put them on the same axis. Instead either: (a) normalise all values to a 0-100 index before charting, (b) use a radar chart with normalised values, or (c) create separate charts for each metric. A bar chart mixing £300,000 with a score of 50 is unreadable. Also: when comparing values in a narrow range, set the Y axis min to just below the lowest value so differences are visible, a 0-based axis makes them all look identical.
8. Professional GOV.UK tone. No emojis or traffic light indicators. British English.
9. Concise responses, short prose, not long bullet lists. Tables over 15 rows should be summarised.
10. Don't narrate before a tool call ("Let me look that up", "I'll query the data"). Call the tool; the interface shows what you're doing. Write text only once you have results.
11. ALWAYS state the time period of the data. When summarising an area from mv_area_overview, every metric is a "latest available" snapshot from different years, read the per-metric year/period columns (e.g. earnings_year, gva_year, crime_period) and tell the user which period each key stat is from (e.g. "Median pay: £720/week (2024); Total GVA: £5.2bn (2018)"). Never imply all metrics share the same reference year.
12. Monthly cross-dataset comparisons: INNER JOIN on period_yyyymm, restrict to the common range (up to the smaller MAX(period_yyyymm)) so a dataset with a later month doesn't produce misleading 0s. Present periods via rs_dim_time.display_label, not raw date_name.
13. End every response with exactly 2 follow-up questions, each on its own line starting with "FOLLOWUP:". The first should go deeper into the current topic. The second should cross into a different dataset that could explain or contextualise the findings (e.g. if discussing health, suggest deprivation or earnings; if discussing crime, suggest employment or housing). Follow-up questions must only reference data available in the tables listed above, never suggest topics we don't have data for. Phrase as full standalone questions (e.g. "What are the drivers of wage disparity between Cornwall and England?"). Never shorten to fragments.
14. If an mv_* view or summarise_area fails because a view does not exist, tell the user plainly that the area views aren't available right now, usually because a data load is still running. Don't rebuild area profiles, rankings or national benchmarks from rs_* tables instead. You can still answer a question that one rs_* table covers directly.
15. Write the aggregate query first. Don't pull raw rows with LIMIT 500 to look at them, and don't re-run a long CTE for each view of the same result; add the extra columns and sort once. If a query errors, fix it silently and move on, never tell the user "let me correct that".
16. Composite rankings ("best combination of"): normalise by rank or by a ratio the user would recognise (price-to-earnings, per head), not min-max against the raw maximum, which lets a £900k borough score as "affordable". State the measures and weights in one line. Don't count a measure twice.
17. Say when a change is noise. APS council-level rates have confidence intervals of several points, so a 10 to 20 point employment swing in a few years is sampling error, not progress. Growth from a roll-out base (Universal Credit before 2018, when councils went live at different times) measures roll-out order, not need; start from a year with national coverage or use per-head change.
18. Every figure you quote must come from a query in this conversation or the benchmarks above. No national averages from memory.
"""

TOOLS = [run_sql, describe_schema, create_chart, create_map, create_choropleth, summarise_area, get_uk_facts]
PROMPT_REFRESH_SECONDS = 3600
_MAX_HISTORY = 20


def _make_system_prompt():
    today = date.today()
    dimension_tables, fact_tables = _render_tables()
    return SYSTEM_PROMPT.format(
        today=today.strftime("%d %B %Y"), year=today.year, uk_summary=_load_uk_summary(), year_ranges=_load_year_ranges(),
        dimension_tables=dimension_tables, fact_tables=fact_tables,
        mv_overview_columns=_load_view_columns("mv_area_overview"), mv_timeseries_columns=_load_view_columns("mv_area_timeseries"),
    )


def _load_table_columns() -> dict | None:
    """{rs_* table: [columns]} from information_schema, or None when the query fails."""
    result = execute_and_track(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name ~ '^rs_' "
        "ORDER BY table_name, ordinal_position",
        timeout=30, max_rows=None,
    )
    if "error" in result or not result["rows"]:
        logger.warning("Failed to load rs_* columns: %s", result.get("error"))
        return None
    columns = {}
    for r in result["rows"]:
        columns.setdefault(r["table_name"], []).append(r["column_name"])
    return columns


def _render_tables() -> tuple[str, str]:
    """The dimension and fact table sections: each loaded rs_* table's columns from Redshift and its notes from gold_tables.py."""
    columns = _load_table_columns()
    notes = {gold_tables.rs_table(t): t.get("prompt", "") for t in gold_tables.TABLES}
    # Tables in build order, then any rs_* table with no gold spec; a table not loaded in this deployment is left out
    names = list(notes) + sorted(set(columns or {}) - set(notes))
    if columns is not None:
        names = [n for n in names if n in columns]
    blocks = {"dim": [], "fact": []}
    for name in names:
        cols = ", ".join(columns[name]) if columns else f"use describe_schema('{name}') for columns"
        text = "\n".join([f"{name}: {cols}."] + [f"  {line}" for line in notes.get(name, "").splitlines()])
        blocks["dim" if name.startswith("rs_dim_") else "fact"].append(text)
    return "\n\n".join(blocks["dim"]), "\n\n".join(blocks["fact"])


def _load_view_columns(view: str) -> str:
    result = execute_and_track(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :view ORDER BY ordinal_position",
        parameters={"view": view}, timeout=30, max_rows=None,
    )
    if "error" in result or not result["rows"]:
        logger.warning("Failed to load %s columns: %s", view, result.get("error"))
        return f"use describe_schema('{view}') to get columns"
    return ", ".join(r["column_name"] for r in result["rows"])


def _load_uk_summary() -> str:
    result = execute_and_track("SELECT * FROM mv_uk_summary LIMIT 1", timeout=30)
    if "error" in result or not result["rows"]:
        logger.warning("Failed to load UK summary: %s", result.get("error"))
        return "UK summary unavailable, use the get_uk_facts tool instead."
    return ", ".join(f"{col}: {round(val, 2) if isinstance(val, float) else val}" for col, val in result["rows"][0].items() if val is not None)


def _load_year_ranges() -> str:
    registry_table = os.environ.get("DATA_SOURCE_REGISTRY_TABLE", "")
    if not registry_table:
        return "Year ranges unavailable, check data with describe_schema."
    try:
        table = boto3.resource("dynamodb", region_name=_region).Table(registry_table)
        items, kwargs = [], {"ProjectionExpression": "source_id, min_year, max_year, gold_tables"}
        while True:
            resp = table.scan(**kwargs)
            items += resp.get("Items", [])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        lines = [f"{t}: {item.get('min_year', '?')} to {item.get('max_year', '?')}"
                 for item in sorted(items, key=lambda x: x.get("source_id", ""))
                 for t in item.get("gold_tables", []) if t.startswith("rs_")]
        return "\n".join(lines) if lines else "Year ranges unavailable."
    except Exception as e:
        logger.warning("Failed to load year ranges: %s", e)
        return "Year ranges unavailable, check data with describe_schema."


_SUMMARY_PROMPT = (
    "Summarise the conversation so far. Preserve: table/column names already verified "
    "via describe_schema, key query results and findings, any area names discussed. "
    "Discard: raw JSON tool outputs, full SQL queries, chart configs."
)


def _make_agent(model, name, description):
    return StrandsAgent(
        agent=Agent(
            system_prompt=_make_system_prompt(),
            model=model,
            tools=TOOLS,
            conversation_manager=SummarizingConversationManager(summary_ratio=0.3, preserve_recent_messages=10, summarization_system_prompt=_SUMMARY_PROMPT),
        ),
        name=name,
        description=description,
        # The chat page builds messages from the streaming events and never reads the snapshots
        config=StrandsAgentConfig(emit_messages_snapshot=False),
    )


_agent_smart = _make_agent(model_smart, "govdata-data-agent-smart", "UK government data analyst (complex queries)")
_agent_fast = _make_agent(model_fast, "govdata-data-agent-fast", "UK government data analyst (simple queries)")
_prompt_built_at = time.time()


def _refresh_prompt_if_stale():
    global _prompt_built_at
    if time.time() - _prompt_built_at < PROMPT_REFRESH_SECONDS:
        return
    prompt = _make_system_prompt()
    for a in (_agent_smart, _agent_fast):
        a._system_prompt = prompt
    _prompt_built_at = time.time()
    logger.info("System prompt rebuilt")




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
    _refresh_prompt_if_stale()

    prompt = next((m.content or "" for m in reversed(run_input.messages) if m.role == "user"), "")
    set_query_id(payload.get("runId") or str(uuid.uuid4()))

    complexity = classify_complexity(prompt) if prompt else "smart"
    logger.info("Model: %s | Session: %s", complexity, context.session_id)
    agui_agent = _agent_fast if complexity == "fast" else _agent_smart

    async def stream():
        async for event in agui_agent.run(run_input):
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
