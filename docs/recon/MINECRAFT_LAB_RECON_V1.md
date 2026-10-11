# Minecraft lab recon v1

Run after the dedicated vanilla 1.21.1 + full official Mekanism family test instance launches successfully.

This stage deliberately does not build a palette.

The runner:
1. invokes Universal Modder um scan on the actual test instance;
2. queries Universal Modder knowledge for Minecraft/Mekanism and NeoForge;
3. fingerprints Mekanism Core, Generators, Tools and Additions;
4. auto-locates the real vanilla 1.21.1 client JAR by inspecting contents;
5. indexes classes and semantic resources;
6. selects relevant subsystem classes;
7. runs javap -p -c -s on them;
8. extracts recipes, tags, loot, blockstates and block models;
9. emits a local ZIP under D:\YAN_RECON.

Run:

    cd D:\YAN_AGENT_LAB
    git fetch origin
    git switch yan-minecraft-lab-recon-v1
    git pull
    powershell -ExecutionPolicy Bypass -File .\tools\run_minecraft_lab_recon.ps1

Upload D:\YAN_RECON\minecraft_lab_<timestamp>.zip after completion.
