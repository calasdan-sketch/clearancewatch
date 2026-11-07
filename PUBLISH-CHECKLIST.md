# Publish checklist for clearancewatch (for Dan; nothing here has been run)

**Version to release: 0.2.0.** PyPI has only 0.1.0 (checked 2026-11-07). The repo is already 0.2.0 everywhere (pyproject, `__version__`, CHANGELOG). Nothing is breaking in the Python API. Some behaviours changed (see CHANGELOG), which is why it is a minor bump and not 0.1.1.

## Before you publish
1. Merge branch `expert-2` into `main` on GitHub (GitHub Actions will run the tests on Linux, Windows and macOS for the first time; wait for green. If a Windows test fails, send me the log).
2. In `CHANGELOG.md` change `## 0.2.0 (unreleased)` to `## 0.2.0 (2026-MM-DD)`.
3. In `README.md` delete the "Heads-up" paragraph under Install (it says 0.2.0 is not on PyPI) and the matching "Windows: not run" sentence only if CI went green on Windows.
4. Check the PyPI account for "Calas Automations Inc." has two-factor login on, and use a token limited to this one project (or set up PyPI "Trusted Publishing" for the GitHub repo, which avoids keeping a token at all).

## Commands (run in a fresh folder, in this order)
```
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install build twine
python -m build
twine check dist/*
pip install dist/clearancewatch-0.2.0-py3-none-any.whl     # try it in a new venv first
clearancewatch template -o jobs.json && clearancewatch audit jobs.json --on 2026-02-15
twine upload dist/*          # this is the step that publishes; it cannot be undone (a version number can never be reused)
git tag v0.2.0 && git push origin v0.2.0
```
After upload, in a new venv: `pip install clearancewatch==0.2.0 && clearancewatch --version` should print `clearancewatch 0.2.0`.

Cost: PyPI is free. Nothing in this project calls a paid service.
