from types import SimpleNamespace

import geopandas as gpd
import pytest
from flask import Flask
from google.api_core.exceptions import AlreadyExists

from state_parks import main
from webhook_trigger import main as webhook_main


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


def test_get_park_name_gets_name_without_state_park_suffix():
    title_from_wordpress = {"rendered": "Antelope Island State Park"}
    park_name = main._get_park_name(title_from_wordpress)
    assert park_name == "Antelope Island"


def test_get_park_name_gets_name_without_state_park_museum_suffix():
    title_from_wordpress = {"rendered": "Edge of the Cedars State Park Museum"}
    park_name = main._get_park_name(title_from_wordpress)
    assert park_name == "Edge of the Cedars"


def test_truncate_and_load_with_restore_retries_with_backup(mocker, tmp_path):
    backup_data = gpd.GeoDataFrame(
        {"truncated_name": ["antelope island"]},
        geometry=gpd.points_from_xy([-111.5], [40.7]),
        crs="EPSG:4326",
    )
    new_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"]})
    loader = mocker.Mock()
    loader.working_dir = tmp_path
    loader.truncate_and_load.side_effect = [RuntimeError("append failed"), 3]

    mocker.patch("state_parks.main.pyogrio.list_layers", return_value=[["parks_backup", "Point"]])
    mocker.patch("state_parks.main.gpd.read_file", return_value=backup_data)
    mocker.patch("pathlib.Path.exists", return_value=True)

    with pytest.raises(RuntimeError, match="append failed"):
        main._truncate_and_load_with_restore(loader, new_data_df)

    restored_backup_data = loader.truncate_and_load.call_args_list[1].args[0]

    assert loader.truncate_and_load.call_args_list == [
        mocker.call(new_data_df, save_old=True),
        mocker.call(restored_backup_data),
    ]
    assert "SHAPE" in restored_backup_data.columns
    assert "geometry" not in restored_backup_data.columns
    assert restored_backup_data.geometry.name == "SHAPE"


def test_truncate_and_load_with_restore_logs_failure_details(mocker, tmp_path):
    backup_data = gpd.GeoDataFrame(
        {"truncated_name": ["antelope island"]},
        geometry=gpd.points_from_xy([-111.5], [40.7]),
        crs="EPSG:4326",
    )
    new_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"]})
    primary_error = RuntimeError("append failed")
    loader = mocker.Mock()
    loader.working_dir = tmp_path
    loader.truncate_and_load.side_effect = [primary_error, 3]
    exception_logger = mocker.patch.object(main.module_logger, "exception")

    mocker.patch("state_parks.main.pyogrio.list_layers", return_value=[["parks_backup", "Point"]])
    mocker.patch("state_parks.main.gpd.read_file", return_value=backup_data)
    mocker.patch("pathlib.Path.exists", return_value=True)

    with pytest.raises(RuntimeError, match="append failed"):
        main._truncate_and_load_with_restore(loader, new_data_df)

    exception_logger.assert_any_call(
        "Primary truncate/load failed (%s); attempting restore from save_old backup", primary_error
    )


def test_restore_service_from_backup_errors_when_backup_missing(tmp_path, mocker):
    loader = mocker.Mock()
    loader.working_dir = tmp_path

    with pytest.raises(FileNotFoundError):
        main._restore_service_from_backup(loader)


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


def test_truncate_and_load_with_restore_logs_counts_on_success(mocker):
    new_data_df = gpd.GeoDataFrame({"truncated_name": ["dead horse point"]})
    loader = mocker.Mock()
    loader.truncate_and_load.return_value = 1
    loader.service.query.side_effect = [5, 1]
    info_logger = mocker.patch.object(main.module_logger, "info")

    loaded_count = main._truncate_and_load_with_restore(loader, new_data_df)

    assert loaded_count == 1
    assert loader.service.query.call_args_list == [
        mocker.call(where="1=1", return_count_only=True),
        mocker.call(where="1=1", return_count_only=True),
    ]
    info_logger.assert_any_call("Feature service row count %s: %d", "before load", 5)
    info_logger.assert_any_call("Feature service row count %s: %d", "after successful load", 1)


def test_create_refresh_task_returns_existing_task_for_duplicate_request(mocker):
    client = mocker.Mock()
    client.create_task.side_effect = AlreadyExists("duplicate")
    secrets = {"SA_EMAIL": "worker@example.com"}

    task_name, created = webhook_main._create_refresh_task(client, "antelope-island", secrets)

    assert task_name == webhook_main._get_task_name()
    assert created is False


def test_trigger_returns_already_queued_status_for_duplicate_task(mocker):
    app = Flask(__name__)
    request = SimpleNamespace(
        args={"api_key": "secret"},
        get_json=lambda: {"post": {"post_name": "antelope-island"}},
    )
    mocker.patch(
        "webhook_trigger.main._get_secrets", return_value={"API_KEY": "secret", "SA_EMAIL": "worker@example.com"}
    )
    mocker.patch("webhook_trigger.main.tasks_v2.CloudTasksClient")
    mocker.patch("webhook_trigger.main._create_refresh_task", return_value=(webhook_main._get_task_name(), False))

    with app.app_context():
        response, status_code = webhook_main.trigger(request)

    assert status_code == 200
    assert response.get_json()["enqueue_status"] == "already_queued"
