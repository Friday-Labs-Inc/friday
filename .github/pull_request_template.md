## What

## Why
Closes #

## How it was verified
- [ ] Gate green locally — paste the summary line from `python ci/run_tests.py --site … --app friday --known-red ci/known-red.txt`
- [ ] `bench --site … migrate` clean
- [ ] `code-reviewer` and `security-reviewer` run; every CRITICAL/HIGH fixed (list any MEDIUM left open)
- [ ] Touched a known-red module? It is green and removed from `ci/known-red.txt`

## Migration / operator notes
<!-- patches, renamed endpoints, new settings, anything an operator must do on upgrade -->

## Design docs touched
<!-- docs/design/NN-*.md updated or "none" -->
