#!/usr/bin/env python
# * coding: utf8 *
"""
Webhook trigger: receives an authenticated HTTP request, clears the Cloud Tasks queue,
and enqueues a new task for the state-parks worker service.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import functions_framework
from flask import jsonify, request
from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from . import config

module_logger = logging.getLogger(config.SKID_NAME)


def _get_task_name():
    """Build the singleton Cloud Tasks name used to de-duplicate refresh requests."""

    return f"{config.CLOUD_TASKS_QUEUE}/tasks/{config.TASK_ID}"


def _create_refresh_task(client, post_name, secrets):
    """Create a singleton refresh task or return the existing task name if already queued."""

    worker_url = f"{config.WORKER_URL}?{urlencode({'post_name': post_name})}"
    schedule_time = timestamp_pb2.Timestamp()
    schedule_time.FromDatetime(datetime.now(tz=timezone.utc) + timedelta(seconds=config.QUEUE_DELAY_SECONDS))
    task_name = _get_task_name()
    new_task = tasks_v2.Task(
        name=task_name,
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=worker_url,
            oidc_token=tasks_v2.OidcToken(
                service_account_email=secrets.get("SA_EMAIL"),
                audience=config.WORKER_URL,
            ),
        ),
        schedule_time=schedule_time,
    )

    try:
        created = client.create_task(parent=config.CLOUD_TASKS_QUEUE, task=new_task)
        module_logger.info("Created task %s for post_name '%s'", created.name, post_name)
        return created.name, True
    except AlreadyExists:
        module_logger.info(
            "Task %s already exists; coalescing duplicate request for post_name '%s'", task_name, post_name
        )
        return task_name, False


def _get_secrets():
    """Load secrets from the Cloud Function mount point or the local secrets directory.

    Raises:
        FileNotFoundError: If no secrets file can be found.

    Returns:
        dict: The secrets .json loaded as a dictionary.
    """

    secret_folder = Path("/secrets")

    #: Try to get the secrets from the Cloud Function mount point
    if secret_folder.exists():
        return json.loads(Path("/secrets/app/secrets.json").read_text(encoding="utf-8"))

    #: Otherwise, try to load a local copy for local development
    secret_folder = Path(__file__).parent / "secrets"
    if secret_folder.exists():
        return json.loads((secret_folder / "secrets.json").read_text(encoding="utf-8"))

    raise FileNotFoundError("Secrets folder not found; secrets not loaded.")


@functions_framework.http
def trigger(request):
    """Cloud Run HTTP endpoint that authenticates the caller, clears the Cloud Tasks queue,
    and enqueues a new task targeting the worker service for the given post.

    URL parameters:
        api_key (str): Must match the API_KEY value in secrets.json.
        post_name (str): The WordPress post slug/name to process.

    Returns:
        JSON response with HTTP 200 on success, 401 on auth failure, or 400 on missing parameters.
    """

    secrets = _get_secrets()

    api_key = request.args.get("api_key")
    if api_key != secrets.get("API_KEY"):
        module_logger.error("Authentication failed for incoming request")
        return jsonify({"error": "Invalid Trigger API Key"}), 401

    payload = request.get_json()
    post_name = payload["post"].get("post_name")
    if not post_name:
        module_logger.error("Missing required parameter: post_name")
        return jsonify({"error": "Missing required parameter: post_name"}), 400

    client = tasks_v2.CloudTasksClient()

    task_name, created = _create_refresh_task(client, post_name, secrets)
    status = "queued" if created else "already_queued"

    return jsonify({"status": "ok", "task": task_name, "enqueue_status": status}), 200
