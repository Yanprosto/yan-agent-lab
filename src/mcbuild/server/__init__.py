"""Live build streaming: WebSocket server that drives run_agent() for a connected mod client."""

import os

from mcbuild.server.repair_proof import activate_repair_probe

# The v1.1 repair proof injects a deliberately broken first route plan so that the
# environment builder must diagnose and repair it. Opt-in only: a generator must not
# build a broken branch first by default.
if os.environ.get("YAN_REPAIR_PROBE") == "1":
    activate_repair_probe()
