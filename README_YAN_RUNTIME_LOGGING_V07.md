# YAN Runtime Logging v0.7

Branch: `yan-runtime-logging-v0.7`

Every live websocket session is recorded automatically and published to:

`https://github.com/Yanprosto/yan-runtime-logs`

## Published layout

```text
latest/
  run.json
  events.jsonl
  verdict.json
runs/
  <run_id>/
    run.json
    events.jsonl
    verdict.json
```

`latest/` is replaced on every completed session.
`runs/<run_id>/` is append-only history.

## Captured events

- RUN_START / RUN_END
- REQUEST
- ACTION
- OBSERVATION
- CHAT
- BLOCKS
- FINISH
- ERROR
- EXCEPTION

Action and observation payloads are stored as structured JSON, including inventory contents, energy values, Mekanism mode changes, rollback results, etc.

## Publishing behavior

The server keeps a local copy under `.yan_runtime_runs/` and a local checkout of the log repository under `.yan_runtime_logs_repo/`.

On session completion it:

1. writes the local run artifacts;
2. fetches/resets the runtime-log checkout to `origin/main`;
3. copies the run to `runs/<run_id>/`;
4. replaces `latest/`;
5. commits;
6. pushes to `origin/main`.

Publishing runs in a worker thread after the websocket session completes. A Git failure never changes the Minecraft experiment verdict; the console reports `local-only` and leaves the local artifact intact.

## Default configuration

```text
YAN_RUNTIME_LOGS_ENABLED=1
YAN_RUNTIME_LOGS_REPO=https://github.com/Yanprosto/yan-runtime-logs.git
YAN_RUNTIME_LOGS_BRANCH=main
```

Optional overrides:

```text
YAN_RUNTIME_LOGS_ENABLED=0
YAN_RUNTIME_LOGS_REPO=<other git remote>
YAN_RUNTIME_LOGS_BRANCH=<branch>
YAN_RUNTIME_LOGS_DIR=<local checkout path>
```

## Test

No Java changed in v0.7, so Minecraft does not need a restart.

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-runtime-logging-v0.7
git pull
```

If `mcbuild-server-dev` is already running, the branch switch should trigger its autoreload automatically.
Otherwise:

```powershell
uv run mcbuild-server-dev
```

Run any existing command, for example:

```text
/yansplitexperiment
```

After completion the Python console should print something like:

```text
[yan-runtime] published 20261011T..._splitter_... commit=<sha> branch=main
```

Then `Yanprosto/yan-runtime-logs/latest/` should contain the new run.

After this, the workflow becomes: run experiment -> tell ChatGPT `смотри последний run`.
