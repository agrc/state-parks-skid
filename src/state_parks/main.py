"""
Run the state-parks script as a Cloud Run Job or console entry point.
"""

import json
import logging
import os
import sys
from pathlib import Path
from pprint import pprint
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import arcgis
import functions_framework
import geopandas as gpd
import pandas as pd
from flask import jsonify
from google.cloud import firestore
from palletjack import extract, load, utils

from . import config

module_logger = logging.getLogger(config.SKID_NAME)


def _is_running_in_cloud_run():
    """Return True when executing inside Cloud Run."""

    return bool(os.environ.get("K_SERVICE"))


def _log_duplicate_outgoing_rows(dataframe):
    """Warn if the outgoing dataset contains duplicate keys before loading."""

    duplicate_keys = dataframe[dataframe["truncated_name"].duplicated(keep=False)]["truncated_name"].dropna().unique()
    if len(duplicate_keys) > 0:
        module_logger.warning(
            "Outgoing dataset contains duplicate truncated_name values: %s", ", ".join(duplicate_keys)
        )


def _log_service_feature_count(loader, context):
    """Log the current live feature count without breaking the main load flow."""

    try:
        count = loader.service.query(where="1=1", return_count_only=True)
    except Exception:
        module_logger.exception("Unable to query feature count %s", context)
        return None

    module_logger.info("Feature service row count %s: %d", context, count)
    return count


def _get_sync_state_reference(client):
    """Return the Firestore document shared with the webhook trigger."""

    return client.collection(config.SYNC_STATE_COLLECTION).document(config.SYNC_STATE_DOCUMENT)


def _get_processed_generation(client):
    """Return the highest webhook generation covered by a successful synchronization."""

    snapshot = _get_sync_state_reference(client).get()
    if not snapshot.exists:
        return 0

    return snapshot.to_dict().get("processed_generation", 0)


def _get_latest_generation(client):
    """Return the newest webhook generation observed before starting a synchronization."""

    snapshot = _get_sync_state_reference(client).get()
    if not snapshot.exists:
        return 0

    return snapshot.to_dict().get("latest_generation", 0)


def _mark_generation_processed(client, generation):
    """Advance the completion watermark after a successful synchronization."""

    state_reference = _get_sync_state_reference(client)

    @firestore.transactional
    def update_processed_generation(transaction):
        snapshot = state_reference.get(transaction=transaction)
        state = snapshot.to_dict() if snapshot.exists else {}
        processed_generation = max(state.get("processed_generation", 0), generation)
        transaction.set(state_reference, {"processed_generation": processed_generation}, merge=True)
        return processed_generation

    return update_processed_generation(client.transaction())


def _update_and_add(loader, update_data_df, add_data_df):
    """Update existing parks and add new parks without truncating the service."""

    _log_service_feature_count(loader, "before synchronization")
    _log_duplicate_outgoing_rows(update_data_df)
    _log_duplicate_outgoing_rows(add_data_df)

    updated_count = 0
    if not update_data_df.empty:
        module_logger.info("Updating %d existing rows in the feature service", len(update_data_df))
        try:
            updated_count = loader.update(update_data_df, update_geometry=True)
        except Exception:
            module_logger.exception("Updating existing feature service rows failed")
            raise

    added_count = 0
    if not add_data_df.empty:
        module_logger.info("Adding %d new rows to the feature service", len(add_data_df))
        try:
            added_count = loader.add(add_data_df)
        except Exception:
            module_logger.exception("Adding new feature service rows failed")
            raise

    _log_service_feature_count(loader, "after successful synchronization")
    return updated_count + added_count


def _build_sync_dataframes(merged_data):
    """Build update, add, and skipped-new-park dataframes from the AGOL/WordPress merge."""

    synchronized_data = merged_data.copy()
    synchronized_data["activities"] = (
        synchronized_data["activities_wp"].fillna("").apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
    )
    synchronized_data["facilities"] = (
        synchronized_data["facilities_wp"].fillna("").apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
    )
    synchronized_data["thumbnail_url"] = synchronized_data["thumbnail_url_wp"].fillna("")
    synchronized_data["full_name"] = synchronized_data["title"].apply(
        lambda x: x["rendered"] if isinstance(x, dict) else x
    )
    synchronized_data["link"] = synchronized_data["link_wp"].fillna("")
    synchronized_data["lat"] = pd.to_numeric(synchronized_data["current_conditions.lat"], errors="coerce")
    synchronized_data["long"] = pd.to_numeric(synchronized_data["current_conditions.long"], errors="coerce")

    geometry_copy = synchronized_data[["SHAPE", "lat", "long"]].copy()
    geometry_copy["lat"] = pd.to_numeric(geometry_copy["lat"], errors="coerce")
    geometry_copy["long"] = pd.to_numeric(geometry_copy["long"], errors="coerce")
    valid_geometry_copy = geometry_copy[
        geometry_copy["lat"].between(-90, 90) & geometry_copy["long"].between(-180, 180)
    ].copy()
    valid_geometry_copy["SHAPE"] = gpd.points_from_xy(
        valid_geometry_copy["long"], valid_geometry_copy["lat"], crs="EPSG:4326"
    ).to_crs(merged_data.crs)
    synchronized_data.update(valid_geometry_copy.reindex(columns=["SHAPE"]))

    output_columns = [
        "OBJECTID",
        "truncated_name",
        "label_state",
        "boatramp",
        "campground",
        "link",
        "thumbnail_url",
        "activities",
        "facilities",
        "full_name",
        "lat",
        "long",
        "SHAPE",
    ]
    update_data_df = synchronized_data.query("_merge != 'right_only'").reindex(columns=output_columns)

    add_candidates = synchronized_data.query("_merge == 'right_only'").copy()
    add_indexes = add_candidates.index.intersection(valid_geometry_copy.index)
    add_data_df = add_candidates.loc[add_indexes].reindex(
        columns=[column for column in output_columns if column != "OBJECTID"]
    )
    skipped_adds = add_candidates.loc[~add_candidates.index.isin(add_indexes)]

    return update_data_df, add_data_df, skipped_adds


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


def _initialize():
    """Configure local CLI logging without adding duplicate Cloud Run handlers."""

    if not _is_running_in_cloud_run():
        cli_handler = logging.StreamHandler(sys.stdout)
        cli_handler.setLevel(logging.INFO)
        cli_handler.setFormatter(
            logging.Formatter(
                fmt="%(levelname)-7s %(asctime)s %(name)15s:%(lineno)5s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logging.basicConfig(level=logging.INFO, handlers=[cli_handler])

    skid_logger = logging.getLogger(config.SKID_NAME)
    skid_logger.setLevel(config.LOG_LEVEL)
    palletjack_logger = logging.getLogger("palletjack")
    palletjack_logger.setLevel(config.LOG_LEVEL)

    #: Log any warnings at logging.WARNING
    logging.captureWarnings(True)


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

    generation_value = request.args.get("generation")
    try:
        generation = int(generation_value) if generation_value is not None else None
    except ValueError:
        return jsonify({"error": "Invalid parameter: generation"}), 400

    firestore_client = firestore.Client() if generation is not None else None
    if generation is not None and generation <= _get_processed_generation(firestore_client):
        return jsonify({"status": "already_processed", "post_name": post_name, "generation": generation}), 200

    covered_generation = _get_latest_generation(firestore_client) if firestore_client is not None else None

    #: Set up secrets, tempdir, and logging
    secrets = SimpleNamespace(**_get_secrets())

    with TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)

        _initialize()
        module_logger = logging.getLogger(config.SKID_NAME)

        #: Get our GIS object via the ArcGIS API for Python
        gis = arcgis.gis.GIS(config.AGOL_ORG, secrets.AGOL_USER, secrets.AGOL_PASSWORD)

        module_logger.info(
            "Getting data from WordPress URL %s and endpoint %s", config.WORDPRESS_URL, config.POSTS_ENDPOINT
        )

        parks_wordpress_loader = extract.WordpressRestLoader(config.WORDPRESS_URL)
        parks_posts = parks_wordpress_loader.get_from_endpoint(config.POSTS_ENDPOINT, expand_acf=True)

        #: These are the posts that we want to pull from
        valid_posts = parks_posts.query("status == 'publish' and page_type == 'parent'").copy()

        #: Get the thumbnail URL so we can hotlink directly to it rather than store the image in AGOL
        valid_posts["thumbnail_url"] = valid_posts["featured_media"].apply(
            lambda media_id: (
                parks_wordpress_loader.get_media_item(media_id).media_details.sizes["medium"].source_url
                if media_id
                else ""
            )
        )
        valid_posts["park_name"] = valid_posts["title"].apply(_get_park_name).str.lower()

        #: This controls which fields we're pulling from WordPress
        valid_posts = valid_posts.reindex(
            columns=[
                "id",
                "title",
                "thumbnail_url",
                "activities",
                "facilities",
                "park_name",
                "link",
                "current_conditions.lat",
                "current_conditions.long",
            ]
        )

        module_logger.info("Update triggered by WordPress post: %s", post_name)

        existing_data = (
            gis.content.get(config.PARKS_FEATURE_LAYER_ITEMID).layers[0].query(where="1=1", out_fields="*").sdf
        )
        existing_data_for_merge = existing_data.copy()
        existing_data_for_merge["truncated_name"] = existing_data_for_merge["truncated_name"].str.lower()

        #: We join on the park name with "State Park" stripped off and lowercased.
        merged_data = existing_data_for_merge.merge(
            valid_posts,
            left_on="truncated_name",
            right_on="park_name",
            how="outer",
            suffixes=("", "_wp"),
            indicator=True,
        )

        #: convert to gdf so we can use geopandas stuff
        merged_data = utils.convert_to_gdf(merged_data)

        #: Notify on any parks not present in the spatial data
        missing_geometries = merged_data.query("_merge == 'right_only'")
        if len(missing_geometries) > 0:
            module_logger.warning(
                "The following %d records from WordPress are missing geometry from AGOL and will not be included in the update",
                len(missing_geometries),
            )
            module_logger.warning(
                ", ".join(
                    f"{row.park_name} ({row.id})"
                    for row in missing_geometries[["park_name", "id"]].itertuples(index=False)
                )
            )

        missing_wp_parks = merged_data.query("_merge == 'left_only'")
        if len(missing_wp_parks) > 0:
            module_logger.warning(
                "The following %d records from AGOL are missing in WordPress and will not be updated",
                len(missing_wp_parks),
            )
            module_logger.warning(
                ", ".join(
                    f"{row.truncated_name} ({row.OBJECTID})"
                    for row in missing_wp_parks[["truncated_name", "OBJECTID"]].itertuples(index=False)
                )
            )

        update_data_df, add_data_df, skipped_adds = _build_sync_dataframes(merged_data)
        if len(skipped_adds) > 0:
            module_logger.warning(
                "The following %d records from WordPress are missing valid coordinates and will not be added",
                len(skipped_adds),
            )
            module_logger.warning(
                ", ".join(
                    f"{row.park_name} ({row.id})" for row in skipped_adds[["park_name", "id"]].itertuples(index=False)
                )
            )

        loader = load.ServiceUpdater(gis, config.PARKS_FEATURE_LAYER_ITEMID, working_dir=tempdir_path)
        features_loaded = _update_and_add(loader, update_data_df, add_data_df)

    if firestore_client is not None:
        _mark_generation_processed(firestore_client, covered_generation)

    return_object = {"status": "ok", "post_name": post_name, "features_loaded": features_loaded}
    if generation is not None:
        return_object["generation"] = generation

    try:
        return jsonify(return_object), 200
    except RuntimeError as e:
        # If we are working outside of the Flask application context, we cannot return a JSON response.
        # Instead, we print the return object to the console for debugging purposes.
        if "Working outside of application context" in str(e):
            pprint(return_object)
        else:
            raise


def _get_park_name(title_from_wordpress):
    """Get the park name and strip off "State Park" so that it's just "Dead Horse Point"

    Args:
        title_from_wordpress (str): The post title in WordPress

    Returns:
        str: Title with "State Park" stripped
    """
    rendered_name = title_from_wordpress["rendered"]
    name_prefix = rendered_name.split("State Park")[0]
    return name_prefix.strip()


if __name__ == "__main__":
    mock_request = SimpleNamespace(args={"post_name": "manual_run"})
    process(mock_request)
