# State Parks Skid

[![Push Events](https://github.com/agrc/state-parks-skid/actions/workflows/push.yml/badge.svg)](https://github.com/agrc/state-parks-skid/actions/workflows/push.yml)

A function that pulls data from the Utah State Parks WordPress website and updates a feature service in ArcGIS Online. The skid is automatically run, via a [WP Webhook plugin](https://wp-webhooks.com/), any time a post is edited.

Contacts:

Aaron Mcelwee (DXP Team)

## Overview

This project defines two Cloud Run services and an experience builder app that is embedded in the Utah State Parks website.

### `state-parks-skid`

This function uses palletjack to extract features from the WordPress REST API, transform the data to match the feature service schema, update existing parks in place, and add new parks with valid coordinates without truncating the ArcGIS Online feature service.

### `webhook-trigger`

This function received web hook calls from the WordPress plugin. It then schedules a task to run in a Cloud Tasks Queue five minutes into the future. It also checks for any pending tasks in the queue and cancels them. This way, if multiple webhooks are received in a short period of time, only one execution of the `state-parks-skid` will be triggered.

## Links

### Staging

WordPress Site: <https://stateparks.stage.utah.gov/parks/>
Experience Builder App: <https://utah.maps.arcgis.com/home/item.html?id=496208cbdb3d416ca36f2220bdceef5d/>
Feature Service: <https://utah.maps.arcgis.com/home/item.html?id=45847ee7b6a04361b9dae4ee5340a4f1/>

### Production

WordPress Site: <https://stateparks.utah.gov/parks/>
Feature Service: <https://utah.maps.arcgis.com/home/item.html?id=45847ee7b6a04361b9dae4ee5340a4f1/>

## WordPress Webhook Setup

Settings -> WP Webhooks -> Send Data -> Post updated -> Add Webhook URL

Webhook Name: `agol-update`

Webhook URL: `<webhook-trigger service URL>?api-key=<webhook-trigger service API key>`

The api key is in this project's secrets.

## Development Setup

This all presumes you're working in Visual Studio Code.

1. Create new environment for the project and install Python
   - `conda create --name state-parks python=3.13`
   - `conda activate state-parks`
1. Install both of the `requirements.txt` files in the `src/state_parks` and `src/webhook_trigger` directories
   - `pip install -r src/state_parks/requirements.txt`
   - `pip install -r src/webhook_trigger/requirements.txt`
1. Set config variables and secrets
   - `secrets.json` holds passwords, secret keys, etc, and will not (and should not) be tracked in git
   - `config.py` holds all the other configuration variables that can be publicly exposed in git
   - Copy `secrets_template.json` to `secrets.json` and change/add whatever values are needed for your skid
   - Change/add variables in `config.py` as needed
1. Run the tests in VS Code
   - Testing -> Run Tests

### Running Locally

To run the skid locally, run the "Run state parks skid" configuration in VS Code's debugger.

### Handling Secrets and Configuration Files

Skids use GCP Secrets Manager to make secrets available to the function. They are mounted as local files with a specified mounting directory (`/secrets`). In this mounting scheme, a folder can only hold a single secret, so multiple secrets are handled via nesting folders (ie, `/secrets/app` and `secrets/ftp`). These mount points are specified in the GitHub CI action workflow.

The `secrets.json` folder holds all the login info, etc. A template is available in the repo's root directory. This is read into a dictionary with the `json` package via the `_get_secrets()` function. Other files (`known_hosts`, service account keys) can be handled in a similar manner or just have their path available for direct access.

A separate `config.py` module holds non-secret configuration values. These are accessed by importing the module and accessing them directly.

### Deployment Environments

Non-secret, environment-specific values (WordPress base URL, ArcGIS Online feature layer item ID, and the worker service URL) are committed in each service's `config.py` under `staging` and `production` mappings. The deployed Cloud Function receives a `DEPLOYMENT_ENVIRONMENT` runtime variable that selects which mapping is used.

| Deployment    | Workflow / trigger                                   | `DEPLOYMENT_ENVIRONMENT` |
| ------------- | ---------------------------------------------------- | ------------------------ |
| Staging (dev) | `.github/workflows/push.yml` on `dev`                | `staging`                |
| Production    | `.github/workflows/release.yml` on release published | `production`             |

Local development defaults to `staging` when `DEPLOYMENT_ENVIRONMENT` is not set, so no extra configuration is required to run or test the skid locally.
