"""Refreshes the Redshift objects whose SQL changed between two commits; the Deploy stage runs it after terraform apply.

usage: refresh_changed_sql.py <from-commit> <to-commit>

The pipeline's source artifact is a tree without .git, so the changed files come from the CodeCommit API. A changed
refresh file refreshes its rs_* object. A deleted refresh file, or a change to the external schema or grant file, is a
full refresh. A change to the gold build starts a full ETL run instead and exits without waiting. Any refresh is
followed by gold, which rebuilds the area views. Env: AWS_REGION, PREFIX_CODE.
"""

import json
import os
import re
import sys

import boto3
from botocore.config import Config

PREFIX = os.environ["PREFIX_CODE"]
REFRESH_DIR = "deploy/lambda/redshift-setup/sql/refresh/"
GOLD_DIR = "deploy/lambda/redshift-setup/sql/gold/"
GOLD_BUILD = ("deploy/glue/lib/gold_tables.py", "deploy/glue/lib/gold_build.py")
REFRESH_FILE = re.compile(r"deploy/lambda/redshift-setup/sql/refresh/\d+b?-(rs-[\w-]+)\.sql")


def changed_files(from_commit, to_commit):
    """{path: True if the file still exists at to_commit} for every file that differs between the two commits."""
    codecommit = boto3.client("codecommit")
    files = {}
    kwargs = {"repositoryName": f"{PREFIX}-source", "beforeCommitSpecifier": from_commit, "afterCommitSpecifier": to_commit}
    while True:
        page = codecommit.get_differences(**kwargs)
        for d in page["differences"]:
            path = (d.get("afterBlob") or d.get("beforeBlob"))["path"]
            files[path] = d["changeType"] != "D"
        if not page.get("NextToken"):
            return files
        kwargs["NextToken"] = page["NextToken"]


def plan(files):
    """("etl", None), ("refresh", [rs tables] or [] for a full refresh), ("gold", None) or (None, None) for nothing.

    files maps each changed path to whether it still exists.
    """
    if any(f in GOLD_BUILD for f in files):
        return "etl", None
    tables, full, gold = set(), False, False
    for f, exists in files.items():
        if m := REFRESH_FILE.fullmatch(f):
            if exists:
                tables.add(m.group(1).replace("-", "_"))
            else:
                full = True
        elif f.startswith(REFRESH_DIR):
            full = True
        elif f.startswith(GOLD_DIR):
            gold = True
    if full:
        return "refresh", []
    if tables:
        return "refresh", sorted(tables)
    if gold:
        return "gold", None
    return None, None


def invoke(payload):
    lam = boto3.client("lambda", config=Config(read_timeout=900, retries={"max_attempts": 0}))
    resp = lam.invoke(FunctionName=f"{PREFIX}-lambda-redshift-setup", Payload=json.dumps(payload))
    body = json.loads(resp["Payload"].read())
    if "FunctionError" in resp:
        print(f"redshift-setup {payload}: {body.get('errorMessage', '')[:500]}", flush=True)
        return False
    print(f"redshift-setup {payload}: ok", flush=True)
    return True


def start_full_etl():
    sfn = boto3.client("stepfunctions")
    account = boto3.client("sts").get_caller_identity()["Account"]
    arn = f"arn:aws:states:{os.environ['AWS_REGION']}:{account}:stateMachine:{PREFIX}-sfn-etl-to-gold"
    execution = sfn.start_execution(stateMachineArn=arn, input='{"full": true}')["executionArn"]
    print(f"gold build changed, started a full ETL run: {execution}", flush=True)


def main(from_commit, to_commit):
    if not from_commit:
        print("no previous deploy recorded, nothing to refresh", flush=True)
        return 0
    files = changed_files(from_commit, to_commit)
    print(f"{len(files)} files changed since {from_commit[:7]}", flush=True)
    action, tables = plan(files)
    if action is None:
        print("no Redshift SQL changed", flush=True)
        return 0
    if action == "etl":
        start_full_etl()
        return 0
    if action == "refresh" and not invoke({"action": "refresh", "tables": tables}):
        return 1
    return 0 if invoke({"action": "gold"}) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
