# YAN Python autoreload v0.1

Branch: `yan-dev-autoreload-v0.1`

## New dev command

```powershell
cd D:\YAN_AGENT_LAB
uv run mcbuild-server-dev
```

The wrapper:

- launches the normal `mcbuild-server` on `127.0.0.1:8765`;
- watches `src/mcbuild/**/*.py` for changes;
- restarts only the Python server process when Python code changes;
- keeps Minecraft running;
- reuses the same port after the child exits;
- restarts the child if it crashes;
- exits cleanly on Ctrl+C.

Java/NeoForge changes still require:

```powershell
cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

and a Minecraft restart.

## Expected console output

```text
[yan-dev] watching D:\YAN_AGENT_LAB\src\mcbuild
[yan-dev] starting: ... -m mcbuild.server.ws_server --host 127.0.0.1 --port 8765
mcbuild server listening on ws://127.0.0.1:8765 (...)

[yan-dev] change detected: src\mcbuild\server\ws_server.py
[yan-dev] stopping mcbuild-server...
[yan-dev] starting: ...
mcbuild server listening on ws://127.0.0.1:8765 (...)
```

Use the regular `uv run mcbuild-server` for non-reloading/production-style runs.
