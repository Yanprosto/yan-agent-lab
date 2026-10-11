# Runtime registry recon v1

This stage runs inside the actual NeoForge 1.21.1 laboratory instance.

Command:

```text
/yanregistrydump
```

It exports authoritative runtime facts for every registered block/item:

- registry id and namespace;
- runtime mod list/version;
- block and item tags;
- default BlockState;
- full state-property domains;
- item counterpart and stack size;
- light emission;
- destroy speed;
- explosion resistance;
- occlusion / collision / replaceability;
- fluid-state presence;
- whether the block implements EntityBlock;
- BlockEntity class/type when it can be instantiated safely.

It deliberately does not classify blocks as architecture/functional/prestige. That
semantic layer comes only after runtime truth is joined with static recon, recipes and
the existing Mekanism audit.

## Build/install

```powershell
cd D:\YAN_AGENT_LAB
git fetch origin
git switch yan-runtime-registry-recon-v1
git pull

powershell -ExecutionPolicy Bypass -File .\tools\build_install_registry_bridge.ps1
```

Launch the controlled test instance, enter a world and run:

```text
/yanregistrydump
```

Then locate the newest dump:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\find_runtime_registry_dump.ps1
```

Do not commit the raw runtime dump yet. The next stage will distill/join it with the
existing compact static oracle.
