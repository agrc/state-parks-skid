"""
config.py: Configuration values. Secrets to be handled with Secrets Manager
"""

import logging
import os
import socket
import urllib.request

SKID_NAME = "webhook-trigger"

try:
    url = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
    req = urllib.request.Request(url)
    req.add_header("Metadata-Flavor", "Google")
    with urllib.request.urlopen(req, timeout=15) as response:
        project_id = response.read().decode()
        if not project_id:
            raise ValueError
        HOST_NAME = project_id
except (OSError, ValueError):
    HOST_NAME = socket.gethostname()

LOG_LEVEL = logging.DEBUG

#: Cloud Tasks queue path: projects/{project}/locations/{region}/queues/{queue_name}
CLOUD_TASKS_QUEUE = f"projects/{HOST_NAME}/locations/us-central1/queues/cloud-tasks-queue-skid"

ENVIRONMENTS = {
    "staging": {
        "worker_url": "https://state-parks-skid-pn4shk4ynq-uc.a.run.app",
    },
    "production": {
        # TODO: Set the production worker URL after the first deployment
        "worker_url": "",
    },
}

DEPLOYMENT_ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "staging")
if DEPLOYMENT_ENVIRONMENT not in ENVIRONMENTS:
    raise ValueError(
        f"Unsupported DEPLOYMENT_ENVIRONMENT: {DEPLOYMENT_ENVIRONMENT!r}. Expected one of: {', '.join(ENVIRONMENTS)}"
    )

#: URL of the state-parks worker Cloud Run function
WORKER_URL = ENVIRONMENTS[DEPLOYMENT_ENVIRONMENT]["worker_url"]

QUEUE_DELAY_SECONDS = 5 * 60
TASK_ID = "state-parks-refresh"
