import geopandas as gpd
import pandas as pd
import pytest
from flask import Flask, request

from state_parks import main


def test_process_returns_bad_request_for_invalid_generation(mocker):
    app = Flask(__name__)
    get_secrets = mocker.patch.object(main, "_get_secrets")

    with app.test_request_context("/?post_name=antelope-island&generation=invalid"):
        response, status_code = main.process(request)

    assert status_code == 400
    assert response.get_json() == {"error": "Invalid parameter: generation"}
    get_secrets.assert_not_called()


def test_process_returns_already_processed_without_running_synchronization(mocker):
    app = Flask(__name__)
    firestore_client = mocker.Mock()
    mocker.patch.object(main.firestore, "Client", return_value=firestore_client)
    mocker.patch.object(main, "_get_processed_generation", return_value=42)
    get_secrets = mocker.patch.object(main, "_get_secrets")

    with app.test_request_context("/?post_name=antelope-island&generation=42"):
        response, status_code = main.process(request)

    assert status_code == 200
    assert response.get_json() == {
        "status": "already_processed",
        "post_name": "antelope-island",
        "generation": 42,
    }
    get_secrets.assert_not_called()


def test_get_secrets_from_gcp_location(mocker):
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.read_text", return_value='{"foo":"bar"}')

    secrets = main._get_secrets()

    assert secrets == {"foo": "bar"}


def test_get_secrets_from_local_location(mocker):
    exists_mock = mocker.Mock(side_effect=[False, True])
    mocker.patch("pathlib.Path.exists", new=exists_mock)
    mocker.patch("pathlib.Path.read_text", return_value='{"foo":"bar"}')

    secrets = main._get_secrets()

    assert secrets == {"foo": "bar"}
    assert exists_mock.call_count == 2


def test_get_processed_generation_returns_zero_when_no_state_document(mocker):
    client = mocker.Mock()
    snapshot = mocker.Mock(exists=False)
    client.collection.return_value.document.return_value.get.return_value = snapshot

    generation = main._get_processed_generation(client)

    assert generation == 0


def test_get_processed_generation_reads_completion_watermark(mocker):
    client = mocker.Mock()
    snapshot = mocker.Mock(exists=True)
    snapshot.to_dict.return_value = {"processed_generation": 42}
    client.collection.return_value.document.return_value.get.return_value = snapshot

    generation = main._get_processed_generation(client)

    assert generation == 42


def test_get_latest_generation_reads_pending_watermark(mocker):
    client = mocker.Mock()
    snapshot = mocker.Mock(exists=True)
    snapshot.to_dict.return_value = {"latest_generation": 42}
    client.collection.return_value.document.return_value.get.return_value = snapshot

    generation = main._get_latest_generation(client)

    assert generation == 42


def test_mark_generation_processed_does_not_regress_watermark(mocker):
    client = mocker.Mock()
    transaction = mocker.Mock()
    state_reference = client.collection.return_value.document.return_value
    snapshot = mocker.Mock(exists=True)
    snapshot.to_dict.return_value = {"processed_generation": 42}
    state_reference.get.return_value = snapshot
    client.transaction.return_value = transaction
    mocker.patch("state_parks.main.firestore.transactional", new=lambda function: function)

    generation = main._mark_generation_processed(client, 41)

    assert generation == 42
    transaction.set.assert_called_once_with(state_reference, {"processed_generation": 42}, merge=True)


def test_get_park_name_gets_name_without_state_park_suffix():
    title_from_wordpress = {"rendered": "Antelope Island State Park"}
    park_name = main._get_park_name(title_from_wordpress)
    assert park_name == "Antelope Island"


def test_get_park_name_gets_name_without_state_park_museum_suffix():
    title_from_wordpress = {"rendered": "Edge of the Cedars State Park Museum"}
    park_name = main._get_park_name(title_from_wordpress)
    assert park_name == "Edge of the Cedars"


def test_build_sync_dataframes_updates_adds_and_skips_expected_parks():
    merged_data = gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2, None, None],
            "truncated_name": ["existing", "legacy", None, None],
            "label_state": ["UT", "UT", None, None],
            "boatramp": [False, False, None, None],
            "campground": [True, True, None, None],
            "activities_wp": [["Hiking"], None, ["Boating"], ["Fishing"]],
            "facilities_wp": [["Restroom"], None, ["Marina"], ["Dock"]],
            "thumbnail_url_wp": ["existing.jpg", None, "new.jpg", "skipped.jpg"],
            "title": [
                {"rendered": "Existing State Park"},
                None,
                {"rendered": "New State Park"},
                {"rendered": "Skipped State Park"},
            ],
            "link_wp": ["/existing", None, "/new", "/skipped"],
            "current_conditions.lat": [40.0, None, 41.0, None],
            "current_conditions.long": [-111.0, None, -112.0, None],
            "park_name": ["existing", None, "new", "skipped"],
            "id": [101, None, 102, 103],
            "_merge": ["both", "left_only", "right_only", "right_only"],
        },
        geometry=gpd.GeoSeries(
            gpd.points_from_xy([-110.0, -109.0, None, None], [40.0, 41.0, None, None]), crs="EPSG:4326"
        ),
        crs="EPSG:4326",
    ).rename_geometry("SHAPE")

    update_data_df, add_data_df, skipped_adds = main._build_sync_dataframes(merged_data)

    assert set(update_data_df["OBJECTID"]) == {1, 2}
    assert "OBJECTID" not in add_data_df.columns
    assert add_data_df["full_name"].tolist() == ["New State Park"]
    assert pd.api.types.is_float_dtype(update_data_df["lat"])
    assert pd.api.types.is_float_dtype(update_data_df["long"])
    assert pd.api.types.is_float_dtype(add_data_df["lat"])
    assert pd.api.types.is_float_dtype(add_data_df["long"])
    assert add_data_df.iloc[0].SHAPE.x == -112.0
    assert add_data_df.iloc[0].SHAPE.y == 41.0
    assert skipped_adds["park_name"].tolist() == ["skipped"]

    existing_row = update_data_df.set_index("truncated_name").loc["existing"]
    assert existing_row["lat"] == 40.0
    assert existing_row["long"] == -111.0
    assert existing_row.SHAPE.x == -111.0
    assert existing_row.SHAPE.y == 40.0

    legacy_row = update_data_df.set_index("truncated_name").loc["legacy"]
    assert pd.isna(legacy_row["lat"])
    assert pd.isna(legacy_row["long"])
    assert legacy_row.SHAPE.x == -109.0
    assert legacy_row.SHAPE.y == 41.0
    assert legacy_row["link"] == ""
    assert legacy_row["activities"] == ""
    assert legacy_row["facilities"] == ""


def test_update_and_add_updates_existing_rows_and_adds_new_rows(mocker):
    update_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"], "OBJECTID": [1]})
    add_data_df = gpd.GeoDataFrame({"truncated_name": ["antelope island"]})
    loader = mocker.Mock()
    loader.update.return_value = 1
    loader.add.return_value = 1
    loader.service.query.side_effect = [5, 6]

    loaded_count = main._update_and_add(loader, update_data_df, add_data_df)

    assert loaded_count == 2
    loader.update.assert_called_once_with(update_data_df, update_geometry=True)
    loader.add.assert_called_once_with(add_data_df)
    assert loader.truncate_and_load.call_count == 0


def test_update_and_add_propagates_update_failure(mocker):
    update_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"], "OBJECTID": [1]})
    add_data_df = gpd.GeoDataFrame({"truncated_name": ["antelope island"]})
    update_error = RuntimeError("update failed")
    loader = mocker.Mock()
    loader.update.side_effect = update_error
    exception_logger = mocker.patch.object(main.module_logger, "exception")
    loader.service.query.return_value = 5

    with pytest.raises(RuntimeError, match="update failed"):
        main._update_and_add(loader, update_data_df, add_data_df)

    exception_logger.assert_called_once_with("Updating existing feature service rows failed")
    loader.add.assert_not_called()
    assert loader.truncate_and_load.call_count == 0


def test_update_and_add_propagates_add_failure_after_updates(mocker):
    update_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"], "OBJECTID": [1]})
    add_data_df = gpd.GeoDataFrame({"truncated_name": ["antelope island"]})
    add_error = RuntimeError("add failed")
    loader = mocker.Mock()
    loader.update.return_value = 1
    loader.add.side_effect = add_error
    loader.service.query.return_value = 5
    exception_logger = mocker.patch.object(main.module_logger, "exception")

    with pytest.raises(RuntimeError, match="add failed"):
        main._update_and_add(loader, update_data_df, add_data_df)

    loader.update.assert_called_once_with(update_data_df, update_geometry=True)
    exception_logger.assert_called_once_with("Adding new feature service rows failed")
    assert loader.truncate_and_load.call_count == 0


def test_log_duplicate_outgoing_rows_warns_for_duplicate_keys(mocker):
    logger = mocker.patch.object(main.module_logger, "warning")
    dataframe = gpd.GeoDataFrame({"truncated_name": ["antelope island", "antelope island", "dead horse point"]})

    main._log_duplicate_outgoing_rows(dataframe)

    logger.assert_called_once()


def test_log_service_feature_count_logs_current_count(mocker):
    loader = mocker.Mock()
    loader.service.query.return_value = 42
    logger = mocker.patch.object(main.module_logger, "info")

    count = main._log_service_feature_count(loader, "after successful load")

    assert count == 42
    loader.service.query.assert_called_once_with(where="1=1", return_count_only=True)
    logger.assert_any_call("Feature service row count %s: %d", "after successful load", 42)


def test_update_and_add_skips_empty_batches_and_logs_counts(mocker):
    update_data_df = gpd.GeoDataFrame({"truncated_name": []})
    add_data_df = gpd.GeoDataFrame({"truncated_name": []})
    loader = mocker.Mock()
    loader.service.query.side_effect = [5, 5]
    info_logger = mocker.patch.object(main.module_logger, "info")

    loaded_count = main._update_and_add(loader, update_data_df, add_data_df)

    assert loaded_count == 0
    loader.update.assert_not_called()
    loader.add.assert_not_called()
    assert loader.service.query.call_args_list == [
        mocker.call(where="1=1", return_count_only=True),
        mocker.call(where="1=1", return_count_only=True),
    ]
    info_logger.assert_any_call("Feature service row count %s: %d", "before synchronization", 5)
    info_logger.assert_any_call("Feature service row count %s: %d", "after successful synchronization", 5)
