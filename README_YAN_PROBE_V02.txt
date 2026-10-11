YAN Agent bidirectional probe v0.2

Purpose:
- prove a multi-step ACTION -> OBSERVATION -> decision -> ACTION -> OBSERVATION session
- inspect the actual block under the player's crosshair instead of the player's air cell

Usage:
1) Overlay this zip onto D:\YAN_AGENT_LAB
2) Rebuild mod: cd D:\YAN_AGENT_LAB\mod ; .\gradlew.bat build
3) Replace mcbuild_live-1.0.0.jar in the test instance
4) Run Python server: cd D:\YAN_AGENT_LAB ; uv run mcbuild-server
5) In Minecraft, aim directly at a machine/block within 12 blocks and run /yanprobe

Expected:
- target line names the block under crosshair and BlockEntity class if present
- Python then requests the target's 6-neighbourhood over the same WebSocket
- final line: probe v0.2 PASS: 2 ACTION/OBSERVATION rounds ...
