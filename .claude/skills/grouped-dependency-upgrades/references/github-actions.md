# github-actions adapter notes

There is no local health check. `metrics` is empty and `compare_baseline.py`
says so rather than printing a comfortable zero.

- **Verification is the PR's own CI run.** An action bump either runs or it does
  not, and the workflow tells you within minutes.
- **No `add` command.** The version is a pin in the workflow YAML; edit it
  directly. `manual_edit: true` records that.
- **Cooldown is config-side**, via `.github/dependabot.yml`.
- Group action bumps the same way — one PR for the batch — and expect them to be
  low tier almost always, because most are patches or minors.
- **Every action major is high tier**, like every other major: it stays out of
  the grouped PR and runs alone. `triage_prs.py` already tiers it that way.
  An action that gates a release (`release-please-action`, publish actions) is
  the sharpest case — a broken one is noticed after the release, not before —
  but it is the reason to be careful, not the boundary of the rule.
