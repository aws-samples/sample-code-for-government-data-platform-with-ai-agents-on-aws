"""AgentCore Gateway tool describe_schema: columns of the rs_* tables and mv_* views."""
import logging

import redshift_data

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ALL_SQL = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND (table_name LIKE 'rs\\_%' OR table_name LIKE 'mv\\_%')
    ORDER BY 1, 2
"""
_ONE_SQL = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :table_name
    ORDER BY 1, 2
"""


def handler(event, context):
    arguments = event.get("arguments", event)
    table_name = str(arguments.get("table_name", "")).strip()

    try:
        if table_name:
            _, rows = redshift_data.run(_ONE_SQL, context, parameters={"table_name": table_name})
        else:
            _, rows = redshift_data.run(_ALL_SQL, context)
    except redshift_data.QueryError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("describe_schema failed")
        return {"error": "The schema could not be read, try again."}

    schema = {}
    for row in rows:
        schema.setdefault(row["table_name"], []).append({"name": row["column_name"], "type": row["data_type"]})
    return {"tables": schema, "table_count": len(schema)}
