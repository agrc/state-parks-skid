# State Parks Skid

[![Push Events](https://github.com/agrc/state-parks-skid/actions/workflows/push.yml/badge.svg)](https://github.com/agrc/state-parks-skid/actions/workflows/push.yml)

A function that pulls data from the Utah State Parks WorkPress website and updates a feature service in ArcGIS Online. The skid is automatically run, via a [WP Webhook plugin](https://wp-webhooks.com/), any time a post is edited.

## Overview

This project defines two Cloud Run services:

### `state-parks-skid`

This function uses palletjack to extract features from the WordPress REST API, transform the data to match the feature service schema, and truncate/load it into ArcGIS Online.

### `webhook-trigger`

This function received web hook calls from the WordPress plugin. It then schedules a task to run in a Cloud Tasks Queue five minutes into the future. It also checks for any pending tasks in the queue and cancels them. This way, if multiple webhooks are received in a short period of time, only one execution of the `state-parks-skid` will be triggered.

## Development Setup

This all presumes you're working in Visual Studio Code.

1. Create new environment for the project and install Python
   - `conda create --name state-parks python=3.13`
   - `conda activate state-parks`
1. Open the repo folder in VS Code
1. Install the skid in your conda environment as an editable package for development
   - This will install all the normal and development dependencies (palletjack, supervisor, etc)
   - `cd c:\path\to\repo`
   - `pip install -e .[tests]`
   - add any additional project requirements to the `setup.py:install_requires` list
1. Set config variables and secrets
   - `secrets.json` holds passwords, secret keys, etc, and will not (and should not) be tracked in git
   - `config.py` holds all the other configuration variables that can be publicly exposed in git
   - Copy `secrets_template.json` to `secrets.json` and change/add whatever values are needed for your skid
   - Change/add variables in `config.py` as needed
1. Run the tests in VS Code
   - Testing -> Run Tests

### Running Locally

Because the Docker container is just `pip install`ing your module and running the entry point defined in `setup.py`, you can generally run your code locally by doing the same (it should already be installed in your conda environment in the development steps listed above). You can run it via VS Code's debugger as well running it as a module. A `.main` entry point is predefined in `.vscode/launch.json`.

To test it in the Docker container's environment, you can run use the `Dockerfile` to create a container and run it locally using a tool like [Podman](https://podman.io/).

### Handling Secrets and Configuration Files

Skids use GCP Secrets Manager to make secrets available to the function. They are mounted as local files with a specified mounting directory (`/secrets`). In this mounting scheme, a folder can only hold a single secret, so multiple secrets are handled via nesting folders (ie, `/secrets/app` and `secrets/ftp`). These mount points are specified in the GitHub CI action workflow.

The `secrets.json` folder holds all the login info, etc. A template is available in the repo's root directory. This is read into a dictionary with the `json` package via the `_get_secrets()` function. Other files (`known_hosts`, service account keys) can be handled in a similar manner or just have their path available for direct access.

A separate `config.py` module holds non-secret configuration values. These are accessed by importing the module and accessing them directly.
