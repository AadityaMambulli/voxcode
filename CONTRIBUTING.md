# Contributing

Thanks for helping improve voxcode.

## Development setup

Use Python 3.10-3.13 and the repository virtual environment:

```powershell
uv pip install -e ".[dev]"
```

Run the checks that do not require real hardware:

```powershell
ruff check .
mypy src
pytest -m "not hardware"
python scripts/validate_manifests.py
```

Hardware tests are opt-in:

```powershell
pytest -m hardware
```

Do not commit model caches, audio recordings, credentials, local Claude
settings, or `.venv` files. Keep voice input untrusted and preserve the
no-auto-Enter default.
