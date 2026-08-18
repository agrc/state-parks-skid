"""
config.py: Configuration values. Secrets to be handled with Secrets Manager
"""

import logging
import os
import socket
import urllib.request

SKID_NAME = "state-parks"

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

AGOL_ORG = "https://utah.maps.arcgis.com"
SENDGRID_SETTINGS = {  #: Settings for SendGridHandler
    "from_address": "noreply@utah.gov",
    "to_addresses": "",
    "prefix": f"{SKID_NAME} on {HOST_NAME}: ",
}
LOG_LEVEL = logging.DEBUG
LOG_FILE_NAME = "log"

POSTS_ENDPOINT = "parks"

ENVIRONMENTS = {
    "staging": {
        "wordpress_url": "https://stateparks.stage.utah.gov",
        "parks_feature_layer_itemid": "f48539a42c714223ad67e0e6727051cf",
    },
    "production": {
        "wordpress_url": "https://stateparks.utah.gov",
        "parks_feature_layer_itemid": "45847ee7b6a04361b9dae4ee5340a4f1",
    },
}

DEPLOYMENT_ENVIRONMENT = os.environ.get("DEPLOYMENT_ENVIRONMENT", "staging")
if DEPLOYMENT_ENVIRONMENT not in ENVIRONMENTS:
    raise ValueError(
        f"Unsupported DEPLOYMENT_ENVIRONMENT: {DEPLOYMENT_ENVIRONMENT!r}. Expected one of: {', '.join(ENVIRONMENTS)}"
    )

WORDPRESS_URL = ENVIRONMENTS[DEPLOYMENT_ENVIRONMENT]["wordpress_url"]
PARKS_FEATURE_LAYER_ITEMID = ENVIRONMENTS[DEPLOYMENT_ENVIRONMENT]["parks_feature_layer_itemid"]

#: Cloud Tasks queue path: projects/{project}/locations/{region}/queues/{queue_name}
CLOUD_TASKS_QUEUE = f"projects/{HOST_NAME}/locations/us-central1/queues/state-parks-queue"
SYNC_STATE_COLLECTION = "state-parks-sync-state"
SYNC_STATE_DOCUMENT = DEPLOYMENT_ENVIRONMENT
