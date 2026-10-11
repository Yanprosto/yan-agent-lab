# Mekanism lab bootstrap

Installs the exact coherent Mekanism family into the dedicated 1.21.1 NeoForge test instance:

- Mekanism
- Mekanism Generators
- Mekanism Tools
- Mekanism Additions

Default target version: `10.7.19.85`.

The script:
- backs up currently installed official Mekanism JARs;
- resolves the exact 1.21.1 NeoForge release through Modrinth's API;
- downloads the primary JAR only;
- verifies SHA-512 against Modrinth metadata;
- removes stale versions of the same official module;
- installs all four modules on one release line.

Run from PowerShell:

```powershell
cd D:\YAN_AGENT_LAB
powershell -ExecutionPolicy Bypass -File .\tools\install_mekanism_lab.ps1
```

Custom mods directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_mekanism_lab.ps1 `
  -ModsDir "C:\path\to\instance\minecraft\mods" `
  -Version "10.7.19.85"
```

After installation, launch the test instance once. Only after the pack starts cleanly do we proceed to targeted Universal Modder recon of the Mekanism family, followed by vanilla recon.
