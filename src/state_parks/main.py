#!/usr/bin/env python
# * coding: utf8 *
"""
Run the SKIDNAME script as a Cloud Run Job or console entry point.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlencode

import arcgis
import functions_framework
from flask import jsonify
from google.cloud import tasks_v2
from palletjack import extract, load, transform, utils

# from supervisor.message_handlers import SendGridHandler
# from supervisor.models import MessageDetails, Supervisor
from . import config, version

module_logger = logging.getLogger(config.SKID_NAME)


def _get_secrets():
    """A helper method for loading secrets from either a GCF mount point or the local src/state_parks/secrets/secrets.json file

    Raises:
        FileNotFoundError: If the secrets file can't be found.

    Returns:
        dict: The secrets .json loaded as a dictionary
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


def _initialize(log_path):
    """A helper method to set up logging and supervisor

    Args:
        log_path (Path): File path for the logfile to be written

    Returns:
        Supervisor: The supervisor object used for sending messages
    """

    skid_logger = logging.getLogger(config.SKID_NAME)
    skid_logger.setLevel(config.LOG_LEVEL)
    palletjack_logger = logging.getLogger("palletjack")
    palletjack_logger.setLevel(config.LOG_LEVEL)

    cli_handler = logging.StreamHandler(sys.stdout)
    cli_handler.setLevel(config.LOG_LEVEL)
    formatter = logging.Formatter(
        fmt="%(levelname)-7s %(asctime)s %(name)15s:%(lineno)5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    cli_handler.setFormatter(formatter)

    log_handler = logging.FileHandler(log_path, mode="w")
    log_handler.setLevel(config.LOG_LEVEL)
    log_handler.setFormatter(formatter)

    skid_logger.addHandler(cli_handler)
    skid_logger.addHandler(log_handler)
    palletjack_logger.addHandler(cli_handler)
    palletjack_logger.addHandler(log_handler)

    #: Log any warnings at logging.WARNING
    #: Put after everything else to prevent creating a duplicate, default formatter
    #: (all log messages were duplicated if put at beginning)
    logging.captureWarnings(True)

    # skid_logger.debug("Creating Supervisor object")
    # skid_supervisor = Supervisor(handle_errors=False)
    # sendgrid_settings = config.SENDGRID_SETTINGS
    # sendgrid_settings["api_key"] = sendgrid_api_key
    # skid_supervisor.add_message_handler(
    #     SendGridHandler(
    #         sendgrid_settings=sendgrid_settings, client_name=config.SKID_NAME, client_version=version.__version__
    #     )
    # )

    # return skid_supervisor


def _remove_log_file_handlers(log_name, loggers):
    """A helper function to remove the file handlers so the tempdir will close correctly

    Args:
        log_name (str): The log file's filename
        loggers (List<str>): The loggers that are writing to log_name
    """

    for logger in loggers:
        for handler in logger.handlers:
            try:
                if log_name in handler.stream.name:
                    logger.removeHandler(handler)
                    handler.close()
            except Exception:
                pass


@functions_framework.http
def process(request):
    """Cloud Run HTTP endpoint that updates the AGOL feature service with data from WordPress

    URL parameters:
        post_name (str): The WordPress post slug/name identifying the park triggering the update.

    Returns:
        JSON response with HTTP 200 on success or 400 on missing parameters.
    """

    post_name = request.args.get("post_name")
    if not post_name:
        return jsonify({"error": "Missing required parameter: post_name"}), 400

    #: Set up secrets, tempdir, supervisor, and logging
    start = datetime.now()

    secrets = SimpleNamespace(**_get_secrets())

    with TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)
        log_name = f"{config.LOG_FILE_NAME}_{start.strftime('%Y%m%d-%H%M%S')}.txt"
        log_path = tempdir_path / log_name

        _initialize(log_path)
        # skid_supervisor = _initialize(log_path, secrets.SENDGRID_API_KEY)
        module_logger = logging.getLogger(config.SKID_NAME)

        #: Get our GIS object via the ArcGIS API for Python
        gis = arcgis.gis.GIS(config.AGOL_ORG, secrets.AGOL_USER, secrets.AGOL_PASSWORD)

        module_logger.info(
            "Getting data from WordPress URL %s and endpoint %s", config.WORDPRESS_URL, config.POSTS_ENDPOINT
        )

        parks_wordpress_loader = extract.WordpressRestLoader(config.WORDPRESS_URL)
        parks_posts = parks_wordpress_loader.get_from_endpoint(config.POSTS_ENDPOINT, expand_acf=True)
        valid_posts = parks_posts.query("status == 'publish' and page_type == 'parent'").copy()

        valid_posts["thumbnail_url"] = valid_posts["featured_media"].apply(
            lambda media_id: (
                parks_wordpress_loader.get_media_item(media_id).media_details.sizes["medium"].source_url
                if media_id
                else ""
            )
        )
        valid_posts["park_name"] = valid_posts["title"].apply(_get_park_name).str.lower()
        valid_posts = valid_posts.reindex(
            columns=["title", "thumbnail_url", "activities", "facilities", "park_name", "link"]
        )

        module_logger.info("Update triggered by WordPress post: %s", post_name)

        existing_data = (
            gis.content.get(config.PARKS_FEATURE_LAYER_ITEMID).layers[0].query(where="1=1", out_fields="*").sdf
        )
        existing_data["truncated_name"] = existing_data["truncated_name"].str.lower()

        merged_data = existing_data.merge(
            valid_posts,
            left_on="truncated_name",
            right_on="park_name",
            how="outer",
            suffixes=("", "_wp"),
            indicator=True,
        )

        #: Notify on any parks not present in the spatial data
        missing_geometries = merged_data.query("_merge == 'right_only'")
        if len(missing_geometries) > 0:
            module_logger.warning(
                "The following %d records from WordPress are missing geometry and will not be included in the update",
                len(missing_geometries),
            )
            module_logger.warning(", ".join(list(missing_geometries["park_name"])))

        #: overwrite all parks, not just the ones we have data for. This will remove any data that was removed from WP
        valid_merged_data = merged_data.query("_merge != 'right_only'").copy()
        valid_merged_data["activities"] = (
            valid_merged_data["activities_wp"].fillna("").apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
        )
        valid_merged_data["facilities"] = (
            valid_merged_data["facilities_wp"].fillna("").apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
        )
        valid_merged_data["thumbnail_url"] = valid_merged_data["thumbnail_url_wp"].fillna("")
        valid_merged_data["full_name"] = valid_merged_data["title"].apply(
            lambda x: x["rendered"] if isinstance(x, dict) else x
        )
        valid_merged_data["link"] = valid_merged_data["link_wp"].fillna("")
        #: If a field name isn't in this list, it will remain in the feature service but be blank for all features.
        new_data_df = valid_merged_data.reindex(
            columns=[
                "OBJECTID",
                "label_state",
                "boatramp",
                "campground",
                "link",
                "thumbnail_url",
                "activities",
                "facilities",
                "truncated_name",
                "full_name",
                "lat",
                "long",
                "SHAPE",
            ]
        )

        loader = load.ServiceUpdater(gis, config.PARKS_FEATURE_LAYER_ITEMID, working_dir=tempdir_path)
        features_loaded = loader.truncate_and_load(new_data_df)

        end = datetime.now()

        # summary_message = MessageDetails()
        # summary_message.subject = "Update Summary"
        # summary_rows = [
        #     f"{config.SKID_NAME} update {start.strftime('%Y-%m-%d')}",
        #     "=" * 20,
        #     "",
        #     f"Triggered by post: {post_name}",
        #     f"Start time: {start.strftime('%H:%M:%S')}",
        #     f"End time: {end.strftime('%H:%M:%S')}",
        #     f"Duration: {str(end - start)}",
        #     f"Total records in WordPress: {len(valid_posts)}",
        #     f"Total records with geometries: {len(valid_merged_data)}",
        #     f"Total records missing geometries: {len(missing_geometries)}",
        #     f"Total records updated/created in AGOL: {features_loaded}",
        # ]

        # summary_message.message = "\n".join(summary_rows)
        # summary_message.attachments = tempdir_path / log_name

        # skid_supervisor.notify(summary_message)

        #: Remove file handler so the tempdir will close properly
        loggers = [logging.getLogger(config.SKID_NAME), logging.getLogger("palletjack")]
        _remove_log_file_handlers(log_name, loggers)

    return jsonify({"status": "ok", "post_name": post_name, "features_loaded": features_loaded}), 200


def _get_park_name(title_from_wordpress):
    rendered_name = title_from_wordpress["rendered"]
    name_prefix = rendered_name.split("State Park")[0]
    return name_prefix.strip()


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
        module_logger.info("Authentication failed for incoming request")
        return jsonify({"error": "Unauthorized"}), 401

    post_name = request.args.get("post_name")
    if not post_name:
        return jsonify({"error": "Missing required parameter: post_name"}), 400

    client = tasks_v2.CloudTasksClient()

    #: Delete all existing tasks in the queue before adding a new one
    existing_tasks = client.list_tasks(parent=config.CLOUD_TASKS_QUEUE)
    for task in existing_tasks:
        client.delete_task(name=task.name)
        module_logger.info("Deleted existing task: %s", task.name)

    #: Build the worker URL with post_name as a query parameter
    worker_url = f"{config.WORKER_URL}?{urlencode({'post_name': post_name})}"
    new_task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": worker_url,
        }
    }

    created = client.create_task(parent=config.CLOUD_TASKS_QUEUE, task=new_task)
    module_logger.info("Created task %s for post_name '%s'", created.name, post_name)

    return jsonify({"status": "ok", "task": created.name}), 200


if __name__ == "__main__":
    mock_request = SimpleNamespace(args={"post_name": "manual_run"})
    process(mock_request)
