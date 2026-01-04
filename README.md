# DI2SE External

External dependencies/libraries used in [DI2SE](https://steffenl.com/projects/dead-island-2-save-editor) by [Steffen André Langnes](https://steffenl.com).

If you're looking for the save editor, downloads or contact information then please visit the [website DI2SE SaveTailor](https://steffenl.com/projects/dead-island-2-save-editor).

## Building

Environment variables can be set before running scripts:

| Name                       | Value                | OS      |
| -------------------------- | -------------------- | ------- |
| `BUILD_SHARED_LIBS`        | `OFF` or `ON`        | Any     |
| `CMAKE_BUILD_TYPE`         | `Debug` or `Release` | Any     |
| `GCLOUD_BUCKET`            | gcloud bucket URI    | Any     |
| `GCLOUD_CREDENTIAL_BASE64` | (secret)             | Any     |
| `VCVARS_ARCH`              | `x64`                | Windows |
| `VCVARS_VERSION`           | `x.y`                | Windows |

Create a virtual environment for Python:

```
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows: ".venv/Scripts/activate"
pip install -r scripts/requirements.txt
```

Run the build script:

```
python scripts/devenv.py python scripts/build.py
```
