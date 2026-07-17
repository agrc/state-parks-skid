from flask import Flask, request
from google.api_core.exceptions import AlreadyExists

from webhook_trigger import main as webhook_main


def test_create_refresh_task_returns_existing_task_for_duplicate_request(mocker):
    client = mocker.Mock()
    client.create_task.side_effect = AlreadyExists("duplicate")
    secrets = {"SA_EMAIL": "worker@example.com"}

    task_name, created = webhook_main._create_refresh_task(client, "antelope-island", secrets)

    assert task_name == webhook_main._get_task_name()
    assert created is False


def test_trigger_returns_already_queued_status_for_duplicate_task(mocker):
    app = Flask(__name__)
    mocker.patch(
        "webhook_trigger.main._get_secrets", return_value={"API_KEY": "secret", "SA_EMAIL": "worker@example.com"}
    )
    mocker.patch("webhook_trigger.main.tasks_v2.CloudTasksClient")
    mocker.patch("webhook_trigger.main._create_refresh_task", return_value=(webhook_main._get_task_name(), False))

    with app.test_request_context("/?api_key=secret", json={"post": {"post_name": "antelope-island"}}):
        response, status_code = webhook_main.trigger(request)

    assert status_code == 200
    assert response.get_json()["enqueue_status"] == "already_queued"
