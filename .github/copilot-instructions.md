# State Parks Skid Copilot Instructions

- This is a Python project with two Cloud Run services: `state_parks` synchronizes WordPress park data to an ArcGIS Online feature service, and `webhook_trigger` schedules synchronization through Cloud Tasks.
- Keep changes focused. Preserve the existing module structure under `src/state_parks` and `src/webhook_trigger`, and prefer small helper functions with pytest coverage for new behavior.
- Treat `config.py` as non-secret configuration only. Never add, modify, or expose real values in `secrets.json`; use the corresponding `secrets_template.json` files for examples.
- Preserve the synchronization safeguards: update existing ArcGIS features in place, add only parks with valid coordinates, and do not reintroduce truncate-and-load behavior.
- Use `pathlib.Path` for file paths, type-friendly pandas/GeoPandas operations for tabular and spatial data, and module loggers for operational failures.
- Add or update focused tests in `tests/test_state_parks.py` when changing service behavior, especially failure paths and external-service interactions. Mock network and cloud SDK calls in tests.
- Run `pytest` before completing Python changes. Follow the configured Ruff line length of 120 characters.
- Check for an existing conda environment called "state-parks" before you try creating a new one on your own.
