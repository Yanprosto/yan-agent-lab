# Visual catalog v1

This stage extracts visual evidence for the same 1559 runtime-registered blocks already present in the semantic catalog.

Sources:
- vanilla 1.21.1 client assets when an asset-bearing client JAR is available;
- launcher asset-index block textures as a vanilla fallback;
- Mekanism Core / Generators / Tools / Additions assets from their installed JARs.

For each block it records:
- blockstate/model references when available;
- texture references actually used;
- source of each texture;
- mean RGB/HSV;
- luminance;
- contrast;
- saturation;
- edge density;
- opacity.

This still does not classify anything as architecture or functional. It only supplies the visual half of the later palette decision.

Run:

    cd D:\YAN_AGENT_LAB
    git fetch origin
    git switch yan-visual-catalog-v1
    git pull
    powershell -ExecutionPolicy Bypass -File .\tools\publish_visual_catalog.ps1

After completion, review coverage. If vanilla visual coverage is weak, fix asset discovery before palette compilation.
