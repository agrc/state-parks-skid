"""
config.py: Configuration values. Secrets to be handled with Secrets Manager
"""

import logging
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
except Exception:
    HOST_NAME = socket.gethostname()

LOG_LEVEL = logging.DEBUG

#: Cloud Tasks queue path: projects/{project}/locations/{region}/queues/{queue_name}
CLOUD_TASKS_QUEUE = f"projects/{HOST_NAME}/locations/us-central1/queues/cloud-tasks-queue-skid"
#: URL of the state-parks worker Cloud Run function
WORKER_URL = "https://state-parks-skid-pn4shk4ynq-uc.a.run.app"

QUEUE_DELAY_SECONDS = 10
