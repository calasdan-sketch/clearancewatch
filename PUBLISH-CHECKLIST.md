# Publish checklist for clearancewatch (for Dan; nothing here has been run for you)

**Version to release: 0.2.0.** PyPI has only 0.1.0 (checked 2026-11-07 and again 2026-11-08). The repo is already 0.2.0 everywhere (pyproject, `__version__`, CHANGELOG, tests that keep them equal). Round 5 added features and fixes but 0.2.0 was never published, so there is no reason to burn another version number. Nothing is breaking in the Python API. Some behaviours changed since 0.1.0 (see "Coming from 0.1.0" in the README), which is why this is 0.2.0 and not 0.1.1.

## What changed in Round 5 that you should know before you publish
- Everything now says the author is **Calas Automations Inc.** (PyPI page, LICENSE, `clearancewatch about`).
- Manitoba WCB is now modelled (your own province). The rules come from the WCB Manitoba page and the Act, both listed in the README table. One thing is marked unverified on purpose: how long a Manitoba clearance letter stays good. Please read that README row and decide if you are comfortable saying it.
- There is a new `import-csv` command for people who keep subs in Excel.
- The tool is **not** legal advice and the README says so. Do not describe it as "WCB compliant" or "WSIB approved" in the PyPI text or anywhere else.

## Before you publish
1. Merge branch `expert-2` into `main` on GitHub. GitHub Actions will run the tests on Linux, Windows and macOS for the first time; wait for green. If a Windows test fails, send me the log. (The new golden-file tests compare exact bytes, so a Windows line-ending problem would show up there first.)
2. In `CHANGELOG.md` change `## 0.2.0 (unreleased)` to `## 0.2.0 (2026-MM-DD)` (use the real date).
3. In `README.md` delete the "Heads-up" paragraph under Install (it says 0.2.0 is not on PyPI) and the matching "Windows: not run" sentence only if CI went green on Windows.
4. Check the PyPI account for "Calas Automations Inc." has two-factor login on, and use a token limited to this one project (or set up PyPI "Trusted Publishing" for the GitHub repo, which avoids keeping a token at all).

## Commands (run in a fresh folder, in this order)
```
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install build twine
python -m build
twine check dist/*
unzip -p dist/clearancewatch-0.2.0-py3-none-any.whl clearancewatch-0.2.0.dist-info/METADATA | head -8   # Author line must read: Calas Automations Inc.
pip install dist/clearancewatch-0.2.0-py3-none-any.whl     # try it in a new venv first
clearancewatch template -o jobs.json && clearancewatch audit jobs.json --on 2026-02-15
twine upload dist/*          # this is the step that publishes; it cannot be undone (a version number can never be reused)
git tag v0.2.0 && git push origin v0.2.0
```
(On Windows, where there is no `unzip`, open the `.whl` with any zip tool and read `METADATA` inside the `.dist-info` folder.)

After upload, in a new venv: `pip install clearancewatch==0.2.0 && clearancewatch --version` should print `clearancewatch 0.2.0`, and `clearancewatch about` should name Calas Automations Inc.

Cost: PyPI is free. Nothing in this project calls a paid service or the internet.
