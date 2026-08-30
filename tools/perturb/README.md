# Perturbation harnesses

These three offline scripts are regression evidence for the safety boundaries that ordinary green
tests can accidentally leave redundant. Each script mutates one current source fragment, runs a
focused test, reports `BITES` only when that test fails, and restores the file before continuing.
They must be run from any directory because each resolves the repository root from its own path:

```text
uv run python tools/perturb/perturb_submit.py
uv run python tools/perturb/perturb_installer.py
uv run python tools/perturb/perturb_upgrade.py
```

The scripts never call a real LEARN instance, PyPI, or an installer network endpoint. A `SKIP` or
`SILENT` result is a failed proof and must be investigated before release work continues.
