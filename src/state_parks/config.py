"""
config.py: Configuration values. Secrets to be handled with Secrets Manager
"""

import logging
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
except Exception:
    HOST_NAME = socket.gethostname()

AGOL_ORG = "https://utah.maps.arcgis.com"
SENDGRID_SETTINGS = {  #: Settings for SendGridHandler
    "from_address": "noreply@utah.gov",
    "to_addresses": "",
    "prefix": f"{SKID_NAME} on {HOST_NAME}: ",
}
LOG_LEVEL = logging.DEBUG
LOG_FILE_NAME = "log"

# TODO: vary this based on environment (staging vs production)
WORDPRESS_URL = "https://stateparks.stage.utah.gov"
POSTS_ENDPOINT = "parks"

# TODO: vary this based on environment (staging vs production)
PARKS_FEATURE_LAYER_ITEMID = "45847ee7b6a04361b9dae4ee5340a4f1"

#: Cloud Tasks queue path: projects/{project}/locations/{region}/queues/{queue_name}
CLOUD_TASKS_QUEUE = f"projects/{HOST_NAME}/locations/us-central1/queues/state-parks-queue"
