"""Writes to the bronze layer of the datalake bucket, with one log line and one return shape for every ingest Lambda."""
import hashlib
import json
import logging
import os

import boto3

logger = logging.getLogger()
s3 = boto3.client("s3")

BUCKET = os.environ["DATALAKE_BUCKET"]
# Metadata key for the body's SHA-256; an unchanged file isn't rewritten and keeps the LastModified the ETL's change detection reads
HASH_KEY = "sha256"


def _unchanged(key, digest):
    """True when the object at key was written with this digest."""
    try:
        return s3.head_object(Bucket=BUCKET, Key=key).get("Metadata", {}).get(HASH_KEY) == digest
    except s3.exceptions.ClientError as e:
        # Without s3:ListBucket a missing key is a 403, not a 404
        if e.response["Error"]["Code"] in ("403", "404", "NoSuchKey"):
            return False
        raise


def _skip(key, size):
    logger.info(json.dumps({"message": "Unchanged, not rewritten", "s3_key": key, "bytes": size}))


def put(key, body, content_type="text/csv", **extra_args):
    """Write bytes to key unless they match what's there, and return the byte count."""
    digest = hashlib.sha256(body).hexdigest()
    if _unchanged(key, digest):
        _skip(key, len(body))
        return len(body)
    metadata = {**extra_args.pop("Metadata", {}), HASH_KEY: digest}
    s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type, Metadata=metadata, **extra_args)
    return len(body)


def upload(key, fileobj, content_type="text/csv", metadata=None):
    """Stream a seekable file object to key unless it matches what's there, multipart for large bodies, and return the byte count."""
    size = fileobj.tell()
    fileobj.seek(0)
    sha = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        sha.update(chunk)
    fileobj.seek(0)
    digest = sha.hexdigest()
    if _unchanged(key, digest):
        _skip(key, size)
        return size
    extra = {"ContentType": content_type, "Metadata": {**(metadata or {}), HASH_KEY: digest}}
    s3.upload_fileobj(fileobj, BUCKET, key, ExtraArgs=extra)
    return size


def list_keys(prefix):
    return [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix) for o in page.get("Contents", [])]


def delete(keys):
    for i in range(0, len(keys), 1000):
        s3.delete_objects(Bucket=BUCKET, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})


def sweep(prefix, keep):
    """Delete every object under prefix not in keep, for sources whose Glue job reads the whole prefix. Returns the deleted keys."""
    stale = [k for k in list_keys(prefix) if k not in keep]
    delete(stale)
    if stale:
        logger.info(json.dumps({"message": "Deleted stale files", "prefix": prefix, "keys": stale}))
    return stale


def exists(key):
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def report(dataset, key=None, **fields):
    """Log what was written and return it as the Lambda result."""
    result = {"statusCode": 200, "dataset": dataset, **({"s3_key": key} if key else {}), **fields}
    logger.info(json.dumps({"message": "Wrote to bronze", **{k: v for k, v in result.items() if k != "statusCode"}}))
    return result
