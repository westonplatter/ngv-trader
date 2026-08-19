# github-actions adapter notes

There is no local health check. `metrics` is empty and `compare_baseline.py`
says so rather than printing a comfortable zero.

- **Verification is the PR's own CI run.** An action bump either runs or it does
  not, and the workflow tells you within minutes.
- **No `add` command.** The version is a pin in the workflow YAML; edit it
  directly. `manual_edit: true` records that.
- **Cooldown is config-side**, via `.github/dependabot.yml`.
- Group action bumps the same way — one PR for the batch — but expect them to be
  low tier almost always. The exception is a major on an action that gates a
  release (`release-please-action`, publish actions): treat those as high and
  let the individual PR run alone.
