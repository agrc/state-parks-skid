#!/usr/bin/env python
# * coding: utf8 *
"""
Run the state-parks script as a Cloud Run Job or console entry point.
"""

import json
import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import arcgis
import functions_framework
import geopandas as gpd
import pyogrio
from flask import jsonify
from palletjack import extract, load, utils

from . import config

module_logger = logging.getLogger(config.SKID_NAME)


def _log_duplicate_outgoing_rows(dataframe):
    """Warn if the outgoing dataset contains duplicate keys before loading."""

    duplicate_keys = dataframe[dataframe["truncated_name"].duplicated(keep=False)]["truncated_name"].dropna().unique()
    if len(duplicate_keys) > 0:
        module_logger.warning("Outgoing dataset contains duplicate truncated_name values: %s", ", ".join(duplicate_keys))


def _log_service_feature_count(loader, context):
    """Log the current live feature count without breaking the main load flow."""

    try:
        count = loader.service.query(where="1=1", return_count_only=True)
    except Exception:
        module_logger.exception("Unable to query feature count %s", context)
        return None

    module_logger.info("Feature service row count %s: %d", context, count)
    return count


def _restore_service_from_backup(loader):
    """Restore the feature service from palletjack's save_old backup.gdb artifact."""

    backup_path = Path(loader.working_dir) / "backup.gdb"
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup geodatabase not found at {backup_path}")

    layers = pyogrio.list_layers(backup_path)
    if len(layers) == 0:
        raise ValueError(f"No layers found in backup geodatabase {backup_path}")

    backup_layer = layers[0][0]
    module_logger.info("Restoring feature service from %s layer %s", backup_path, backup_layer)
    backup_data = gpd.read_file(backup_path, layer=backup_layer, engine="pyogrio")

    return loader.truncate_and_load(backup_data)


def _truncate_and_load_with_restore(loader, new_data_df):
    """Load new data with a save_old backup and attempt restore if append fails."""

    module_logger.info("Loading %d rows into the feature service", len(new_data_df))
    _log_duplicate_outgoing_rows(new_data_df)
    _log_service_feature_count(loader, "before load")

    try:
        loaded_count = loader.truncate_and_load(new_data_df, save_old=True)
        _log_service_feature_count(loader, "after successful load")
        return loaded_count
    except Exception:
        module_logger.exception("Primary truncate/load failed; attempting restore from save_old backup")
        try:
            restored_count = _restore_service_from_backup(loader)
            module_logger.error("Restore succeeded with %d rows", restored_count)
            _log_service_feature_count(loader, "after restore")
        except Exception:
            module_logger.exception("Restore failed after primary truncate/load failure")
            _log_service_feature_count(loader, "after failed restore")
        raise


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
    """A helper method to set up logging"""

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

    skid_logger.addHandler(cli_handler)
    palletjack_logger.addHandler(cli_handler)

    #: Log any warnings at logging.WARNING
    #: Put after everything else to prevent creating a duplicate, default formatter
    #: (all log messages were duplicated if put at beginning)
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

        existing_data = gis.content.get(config.PARKS_FEATURE_LAYER_ITEMID).layers[0].query(where="1=1", out_fields="*").sdf
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
        valid_merged_data["lat"] = valid_merged_data["current_conditions.lat"].fillna("")
        valid_merged_data["long"] = valid_merged_data["current_conditions.long"].fillna("")

        geometry_copy = valid_merged_data[["SHAPE", "lat", "long"]].copy()
        valid_geometry_copy = geometry_copy[(geometry_copy["lat"] != "") & (geometry_copy["long"] != "")].copy()
        valid_geometry_copy["SHAPE"] = gpd.points_from_xy(
            valid_geometry_copy["long"], valid_geometry_copy["lat"], crs="EPSG:4326"
        ).to_crs(merged_data.crs)
        valid_merged_data = valid_merged_data.drop(columns=["lat", "long"])

        valid_merged_data.update(valid_geometry_copy.reindex(columns=["SHAPE"]))

        #: If a field name isn't in this list, it will remain in the feature service but be blank for all features.
        new_data_df = valid_merged_data.reindex(
            columns=[
                "OBJECTID",
                "truncated_name",  # join key between wordpress and existing data
                # these fields are preserved from the existing data
                "label_state",
                "boatramp",
                "campground",
                # these fields are overwritten with wordpress data
                "link",
                "thumbnail_url",
                "activities",
                "facilities",
                "full_name",
                "lat",
                "long",
                "SHAPE",  # overwritten by wordpress lat/long data if present
            ]
        )

        loader = load.ServiceUpdater(gis, config.PARKS_FEATURE_LAYER_ITEMID, working_dir=tempdir_path)
        features_loaded = _truncate_and_load_with_restore(loader, new_data_df)

    return jsonify({"status": "ok", "post_name": post_name, "features_loaded": features_loaded}), 200


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
