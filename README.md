# UGRC Palletjack Skid Starter Template

[![Push Events](https://github.com/agrc/skid/actions/workflows/push.yml/badge.svg)](https://github.com/agrc/skid/actions/workflows/push.yml)

A template for building skids that use palletjack to update AGOL data from a tabular data source and that are run as Google Cloud Run Jobs

For an example of a working skid, see [nfhl-skid](https://github.com/agrc/nfhl-skid) or [uocc-skid](https://github.com/agrc/uocc-skid).

## Creating a Git Repository

The first step in creating a skid is to create a new repository in GitHub that uses this repo as a template. You'll then clone the repo to your computer and start developing.

See [this answer](https://stackoverflowteams.com/c/ugrc/a/185/7) on our Stack Overflow for GitHub repo creation via Terraform (the preferred way).

## Initial Skid Development

You'll need to do a few steps to set up your environment to develop a skid. You may also want to make sure you've got the skid working locally before adding the complexity of the cloud function.

This all presumes you're working in Visual Studio Code.

1. Create new environment for the project and install Python
   - `conda create --name PROJECT_NAME python=3.13`
   - `conda activate PROJECT_NAME`
1. Open the repo folder in VS Code
1. Rename `src/skidname` folder to your desired skid name
1. Edit the `setup.py:name, url, description, keywords, and entry_points` to reflect your new skid name
1. Edit the `test_skidname.py` to match your skid name.
   - You will have one `test_filename.py` file for each program file in your `src` directory and you will write tests for the specific file in the `test_filename.py` file
1. Reset the version to 1.0.0 in `version.py`
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
1. Write your skid-specific code inside `process()` in `main.py`
   - If it makes your code cleaner, you can write other methods and call them within `process()`
   - Any `print()` statements should instead use `module_logger.info/debug`. The loggers set up in the `_initialize()` method will write to both standard out (the terminal) and to a log file.
   - Add any captured statistics (number of rows updated, etc) to the `summary_rows` list near the end of `process()` to add them to the email message summary (the log file is already included as an attachment)
1. Run the tests in VS Code
   - Testing -> Run Tests

## Running it as a Google Cloud Run Job

### Setup Cloud Dev/Prod Environments in Google Cloud Platform

Skids run as Cloud Run Jobs triggered by Cloud Scheduler on a regular schedule.

Cloud Run jobs run in a Docker container built using the project's `Dockerfile`. The GitHub deploy action in `.github/actions/deploy/action.yml` handles creating the container, setting the container's resource limits, and setting up Cloud Scheduler. It uses the following GitHub secrets to do this, which should all be set as part of the Terraform repo creation:

- Identity provider
- GCP service account email
- Project ID
- Storage Bucket ID

Work with the GCP maestros to set up a Google project via terraform. They can use the uocc configuration as a starting point. Skids use some or all of the following GCP resources:

- Cloud Functions (executes the python)
- Cloud Storage (writing the data files and log files for mid-term retention)
  - Set a data retention policy on the storage bucket for file rotation (90 days is good for a weekly process)
- Cloud Scheduler (sends a notification to a pub/sub topic)
- Cloud Pub/Sub (creates a topic that links Scheduler and the cloud function)
- Secret Manager
  - A `secrets.json` with the requisite login info
  - A `known_hosts` file (for loading from sftp) or a service account private key file (for loading from Google Sheets)

### Running Locally

Because the Docker container is just `pip install`ing your module and running the entry point defined in `setup.py`, you can generally run your code locally by doing the same (it should already be installed in your conda environment in the development steps listed above). You can run it via VS Code's debugger as well running it as a module. A `.main` entry point is predefined in `.vscode/launch.json` (be sure to update `skidname` to match the folder name under `/src`).

To test it in the Docker container's environment, you can run use the `Dockerfile` to create a container and run it locally using a tool like [Podman](https://podman.io/).

### Handling Secrets and Configuration Files

Skids use GCP Secrets Manager to make secrets available to the function. They are mounted as local files with a specified mounting directory (`/secrets`). In this mounting scheme, a folder can only hold a single secret, so multiple secrets are handled via nesting folders (ie, `/secrets/app` and `secrets/ftp`). These mount points are specified in the GitHub CI action workflow.

The `secrets.json` folder holds all the login info, etc. A template is available in the repo's root directory. This is read into a dictionary with the `json` package via the `_get_secrets()` function. Other files (`known_hosts`, service account keys) can be handled in a similar manner or just have their path available for direct access.

A separate `config.py` module holds non-secret configuration values. These are accessed by importing the module and accessing them directly.

## Attribution

This project was developed with the assistance of [GitHub Copilot](https://github.com/features/copilot).
