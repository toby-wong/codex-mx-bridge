# Claude Code and Kiro CLI

Claude and Kiro command hooks feed the same state file, SSH transport, and pet
display as Codex. Existing commands still default to Codex. Installation is
explicit per client; MeshClaw/Kiro Crew are not included in this implementation.

## Add hooks to an existing installation

First update the installed bridge and plugin from this checkout:

```sh
bash update.sh
```

Preview the settings changes with the installed launcher:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks --client claude
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks --client kiro \
  --agent-config "$HOME/.kiro/agents/my-agent.json"
```

Replace `my-agent.json` with the existing profile you use. Add `--apply` to each
command to install. Start a new Claude session and a Kiro session using that
profile. Managed policy and the clients' normal trust mechanisms still apply.

Claude defaults to `~/.claude/settings.json`, respects `CLAUDE_CONFIG_DIR`, and
accepts `--claude-settings /absolute/path/settings.local.json` for another
explicit scope. It requires Claude Code 2.1.295 or newer, which supports the
advisory hook-failure setting used here.

Kiro requires an explicit JSON agent profile. The default `--kiro-format v2`
uses its legacy `hooks` object. For an existing profile with a `hooks` array,
use `--kiro-format v3`. That selects a hook format, not an engine upgrade.
V3 profiles with unconverted `allowedTools`/`toolsSettings` and no permissions
block are rejected: Kiro can skip those profiles even when basic validation
passes. Use Kiro's own migration separately if needed. The bridge preserves
permissions, tools, resources, existing hooks, and `kiroUpgrade` metadata.

Choose profiles for standalone Kiro sessions. Installing these hooks into
Crew-generated profiles or also enabling gateway hooks can produce duplicate
observations; this bridge does not infer relationships between those sessions.

The installed launcher records selected configuration paths in
`installation.json`. Future `update.sh` runs refresh all registered targets.
Hooks installed directly from a source checkout reference that checkout and
need manual refresh if it moves.

## Fresh installation

Select both clients in one install, or add `--client codex` to include Codex:

```sh
bash install.sh --client claude --client kiro \
  --agent-config "$HOME/.kiro/agents/my-agent.json"
```

Use `--dry-run` for a preview. On Linux, add `--hooks-only`; the Mac collector
and existing SSH export work for all three clients. Only selected clients'
configuration is changed. A Claude/Kiro-only install does not require Codex or
edit its TOML settings.

The installer checks client versions, validates merged Kiro profiles with the
installed `kiro-cli agent validate`, tests the staged hook entrypoints in
temporary state directories, and then installs definitions. Existing files are
backed up before changes. Reinstalling identical definitions does not rewrite
the configuration.

## Observed events

| Client | Observation |
|---|---|
| Claude | Session start/end, prompt submission, tool start/result/failure, permission request, compaction start/end, child start/stop, turn stop/failure |
| Kiro legacy format | `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop` |
| Kiro current array format | Corresponding PascalCase events, plus `SessionEnd` |

Claude tool events with `agent_id` update the child row. `prompt_id`, when
available, prevents an older turn from overwriting the current one.
`PostToolUseFailure` leaves the session working because the agent can retry;
`StopFailure` displays `TURN ERROR` using the failed pet pose.

`Stop` means the turn reached its stop hook. Another hook can request a
continuation, including at Claude's `SubagentStop`. A subsequent tool-start
event can resume activity; a late tool result alone cannot. Kiro does not gain
an inferred permission-wait, compaction, or subagent status from unrelated fields.

Each client/session/child/optional `--instance` tuple has its own identity.
The new clients' button headers include `Claude` or `Kiro`. Direct local iTerm
focus uses the existing terminal attachment; Herdr button focus remains limited
to Codex. New clients cannot select a Codex pane merely because IDs match.

## Liveness and diagnostics

For process heartbeat and exit tracking, select the client on the launcher too:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx run --client claude -- claude
~/.local/share/codex-mx-bridge/bin/codex-mx run --client kiro -- \
  kiro-cli chat --agent my-agent
```

Without the launcher, rows expire after 15 minutes without events. The launcher
uses the existing 45-second heartbeat expiry and records process exit. Neither
silence nor a heartbeat proves model progress.

`codex-mx status` includes `hook_health` with each client's last accepted event
and receipt time. Handler failures write a generic `hook-claude-error.txt` or
`hook-kiro-error.txt` in the state directory. Check file modification times when
comparing an older error with a newer successful event. Runtime/import failures
that prevent the handler from starting may leave only an old receipt time.

Claude/Kiro hooks emit no stdout and return zero, including malformed input and
state-write failures. Generated shell commands also tolerate a missing runtime.
On macOS/Linux, an internal one-second deadline precedes the configured
two-second host timeout. Hooks never produce approval or continuation decisions.
Prompts, tool arguments/results, transcripts, and assistant text are discarded.

## Remove one integration

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks \
  --client claude --remove --apply
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks \
  --client kiro --agent-config "$HOME/.kiro/agents/my-agent.json" --remove --apply
```

Include the same custom settings path or `--kiro-format v3` used at installation.
Only bridge-owned handlers and their update registration are removed. Removal
does not require the client executable; a deleted Kiro profile can also be
unregistered by its original path.

See [validation evidence and limits](VALIDATION.md) for the distinction between
payload tests, configuration validation, client dispatch, and hardware checks.
