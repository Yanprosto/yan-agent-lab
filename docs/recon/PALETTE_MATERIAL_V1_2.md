# Palette material semantics v1.2

This stage fixes the remaining false bulk candidates without returning to token-based safety.

Runtime registry v2 adds:
- block_class
- block_class_hierarchy

Palette bulk eligibility then uses runtime class ancestry and material tags to keep blocks such as falling blocks, carpets, coral blocks, leaves and wool-like materials out of structural/floor bulk slots.

Selection also performs family diversity: standard color-prefix variants are collapsed to at most two entries per family/slot so one Mekanism Additions plastic family cannot occupy the whole shortlist.

Workflow:

1. Build/install the updated bridge:
   powershell -ExecutionPolicy Bypass -File .\tools\build_install_registry_bridge.ps1
2. Launch the test instance and run:
   /yanregistrydump
3. Back in PowerShell run:
   powershell -ExecutionPolicy Bypass -File .\tools\publish_palette_material_v12.ps1

The generated palette remains fact-grounded; family normalization is used only for shortlist diversity, never for safety permission.
