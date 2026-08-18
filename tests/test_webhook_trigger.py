from flask import Flask, request
from google.api_core.exceptions import AlreadyExists

from webhook_trigger import main as webhook_main


def test_record_webhook_increments_firestore_generation(mocker):
    client = mocker.Mock()
    transaction = mocker.Mock()
    state_reference = client.collection.return_value.document.return_value
    snapshot = mocker.Mock(exists=True)
    snapshot.to_dict.return_value = {"latest_generation": 41}
    state_reference.get.return_value = snapshot
    client.transaction.return_value = transaction
    mocker.patch("webhook_trigger.main.firestore.transactional", new=lambda function: function)

    generation = webhook_main._record_webhook(client, "antelope-island")

    assert generation == 42
    transaction.set.assert_called_once_with(
        state_reference,
        {"latest_generation": 42, "latest_post_name": "antelope-island"},
        merge=True,
    )


def test_create_refresh_task_names_task_for_generation(mocker):
    client = mocker.Mock()
    created_task = mocker.Mock()
    created_task.name = "created-task"
    client.create_task.return_value = created_task
    secrets = {"SA_EMAIL": "worker@example.com"}

    task_name, created = webhook_main._create_refresh_task(client, "antelope-island", secrets, generation=42)

    assert task_name == "created-task"
    assert created is True
    assert client.create_task.call_args.kwargs["task"].name.endswith("/tasks/state-parks-refresh-42")
    assert "generation=42" in client.create_task.call_args.kwargs["task"].http_request.url


def test_create_refresh_task_returns_existing_task_for_duplicate_request(mocker):
    client = mocker.Mock()
    client.create_task.side_effect = AlreadyExists("duplicate")
    secrets = {"SA_EMAIL": "worker@example.com"}

    task_name, created = webhook_main._create_refresh_task(client, "antelope-island", secrets, generation=42)

    assert task_name == webhook_main._get_task_name(42)
    assert created is False


def test_trigger_returns_already_queued_status_for_duplicate_task(mocker):
    app = Flask(__name__)
    mocker.patch(
        "webhook_trigger.main._get_secrets", return_value={"API_KEY": "secret", "SA_EMAIL": "worker@example.com"}
    )
    mocker.patch("webhook_trigger.main.firestore.Client")
    mocker.patch("webhook_trigger.main._record_webhook", return_value=42)
    mocker.patch("webhook_trigger.main._create_refresh_task", return_value=(webhook_main._get_task_name(42), False))

    with app.test_request_context("/?api_key=secret", json={"post": {"post_name": "antelope-island"}}):
        response, status_code = webhook_main.trigger(request)

    assert status_code == 200
    assert response.get_json()["enqueue_status"] == "already_queued"
    assert response.get_json()["generation"] == 42
