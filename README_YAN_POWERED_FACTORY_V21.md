# YAN Powered Multi-Cell Factory v2.1

Branch: `yan-powered-factory-v2.1`

v2.1 accelerates from one production cell to two reusable autonomous cells.

## Mission

```text
/yanmission
```

The agent now commissions:

```text
CELL A: 12 raw iron -> 2 Energized Smelters -> 12 ingots
CELL B: 12 raw iron -> 2 Energized Smelters -> 12 ingots

TOTAL:
2 cells
4 processing machines
24 raw iron
24 iron ingots
```

No player-built fixture is required.

## Energy provisioning

v2.0 exposed an important fact: a Creative Energy Cube placed directly into the world may have zero stored energy.

v2.1 adds:

```text
seed_energy
```

Safety:
- only blocks placed by the current agent session may be seeded;
- capability insertion is attempted first;
- the bridge reads the real post-state;
- if a Mekanism creative container reports acceptance without changing stored energy, the bridge uses the official container API `getEnergyContainer().setEnergy(...)`;
- success requires `energy_after > energy_before`.

Each cell now verifies:

```text
energy source before
→ provision if empty
→ energy source after
→ cable A observation
→ cable B observation
→ smelter A energy
→ smelter B energy
```

Material is not staged until power consumers are actually non-zero.

## Scale-up

Instead of writing a new hand-coded four-machine monolith, v2.1 reuses the existing v2.0 two-line production cell as a module and orchestrates two cells in one mission. This is the first step toward composing verified production skills into larger systems.

## Success contract

```text
cells == 2
machines == 4
input raw iron == 24
output iron ingots == 24
remaining source raw == 0
transit == 0
both power systems commissioned
worldPreserved == true
```

Success saves:

```text
autonomous_multi_cell_factory_v1
```

## Install

Java changed, so rebuild once:

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-powered-factory-v2.1
git pull

cd D:\YAN_AGENT_LAB\mod
.\gradlew.bat build

Copy-Item `
  "D:\YAN_AGENT_LAB\mod\build\libs\mcbuild_live-1.0.0.jar" `
  "C:\Users\yan\AppData\Roaming\ElyPrismLauncher\instances\1.21.1(1)\minecraft\mods\mcbuild_live-1.0.0.jar" `
  -Force
```

Restart Minecraft once.

Stand in a reasonably open area and run:

```text
/yanmission
```

Then say:

```text
смотри последний run
```
