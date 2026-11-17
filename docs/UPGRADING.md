# Upgrading and removing

## Upgrade

Installed with pipx from a GitHub tag (current preview route):

```bash
pipx install --force "git+https://github.com/Sanchit-hub/lean-agent-browser@vX.Y.Z"
leanb setup
```

Once Lean is on PyPI:

```bash
pipx upgrade lean-agent-browser
leanb setup
```

`leanb setup` after an upgrade:
- downloads a new Obscura only if the new version pins a different build (the old one fails its hash check),
- keeps your `~/.lean-browser/config.toml`,
- updates the Claude Code entry if the path of `leanb` changed, and otherwise leaves it alone.

Start a new Claude Code session afterwards. `leanb --version` and `leanb doctor` show the version you're running.

Source checkout: `git pull && ./install.sh`.

## Roll back

Install the previous tag the same way (`pipx install --force "git+...@v0.4.0"`), then `leanb setup`. The
config format has not changed in a breaking way so far; any breaking change will be listed in
[`CHANGELOG.md`](../CHANGELOG.md) with migration steps.

## What changes between versions

[`CHANGELOG.md`](../CHANGELOG.md) lists every release. Versioning:
- patch (0.5.x): fixes, no intended changes to the CLI, config, MCP tools or Python API,
- minor (0.x.0): new features. Before 1.0, a minor release may also change tool parameters, and the
  changelog says how,
- major: breaking changes, after 1.0.

## Remove

```bash
leanb uninstall          # removes the engines (~/.lean-browser/bin, pw-browsers) and the Claude Code entry
leanb uninstall --all    # also removes config, traces and everything else in ~/.lean-browser
pipx uninstall lean-agent-browser
```

`leanb uninstall` lists what it will delete and asks first. It removes only the Claude Code entry named
`lean-browser`; your other MCP servers stay. It never touches your own browser or its profile.
