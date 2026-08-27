# ops-scripts
Personal collection of automation scripts and CLI tools for everyday dev/ops tasks.

## Claude config dir switcher

`sh/apply_claude_settings.sh` switches the active Claude Code config dir (account)
for the whole machine. Pure bash, no dependencies.

Profiles are whatever `~/.claude-<profile>` dirs exist on the machine -- nothing is
hardcoded in the script. Run it with no arguments to list them:

```sh
$ sh/apply_claude_settings.sh
Usage: sh/apply_claude_settings.sh <profile> [--dry-run]
  -n, --dry-run: Show what would change without touching any file

Profiles found on this machine ($HOME/.claude-<profile>):
  default        ~/.claude
  work           ~/.claude-work  (you@example.com)
  personal       ~/.claude-personal  (you@example.net)

$ sh/apply_claude_settings.sh work
```

`default` means the stock `~/.claude`. The account shown next to each profile is read
from that dir's own `.claude.json` (via `jq` or `python3` if either is installed --
it is cosmetic and silently omitted otherwise).

It writes `~/.claude-config-dir.env` and makes `~/.bashrc` source it from the very
top -- that is the only place the value lives.

Why `~/.bashrc` and not `settings.json`: the VS Code extension only injects
`claudeCode.environmentVariables` into the CLI it spawns. The session history in the
sidebar, the `ide/` lock dir, the file-history checkpoints and `settings.json` are all
read by the *extension host*, which falls back to `~/.claude` when the variable is
missing from its own environment. The Remote-SSH server is started by a
non-interactive bash that still sources `~/.bashrc`, so exporting there covers
server -> extension host -> CLI -> integrated terminal from one place.

Switching requires restarting the VS Code server (a window reload is not enough,
since the server is what holds the environment):

```sh
pkill -f '\.vscode-server/(code-[0-9a-f]{40}|cli/servers/[^ ]*/server/bin/code-server)'
```

then reconnect from the client.
