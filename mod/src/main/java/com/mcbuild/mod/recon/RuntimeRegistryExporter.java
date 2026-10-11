package com.mcbuild.mod.recon;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.EntityBlock;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import net.neoforged.fml.ModList;

/**
 * Runtime registry exporter for the controlled YAN lab instance.
 *
 * <p>This deliberately records authoritative runtime registry/state facts only.
 * It does not decide whether a block is "architectural", "expensive", or "safe".
 * Those semantic decisions happen later when this dump is joined with static
 * recon and recipe/progression evidence.</p>
 */
public final class RuntimeRegistryExporter {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private static final DateTimeFormatter FILE_TS =
            DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss").withZone(ZoneOffset.UTC);

    private RuntimeRegistryExporter() {}

    public static ExportResult export(MinecraftServer server, ServerLevel level) throws IOException {
        String generatedAt = Instant.now().toString();
        String fileStamp = FILE_TS.format(Instant.now());

        JsonObject root = new JsonObject();
        root.addProperty("schema_version", 1);
        root.addProperty("kind", "yan_runtime_registry");
        root.addProperty("generated_at", generatedAt);
        root.addProperty("minecraft_version", server.getServerVersion());
        root.addProperty("level", level.dimension().location().toString());

        root.add("mods", exportMods());

        JsonArray blocks = new JsonArray();
        List<Block> sortedBlocks = new ArrayList<>();
        BuiltInRegistries.BLOCK.forEach(sortedBlocks::add);
        sortedBlocks.sort(Comparator.comparing(block -> BuiltInRegistries.BLOCK.getKey(block).toString()));

        int blockEntityProviders = 0;
        int blocksWithItems = 0;
        int blocksWithTags = 0;

        BlockPos probePos = BlockPos.ZERO;

        for (Block block : sortedBlocks) {
            ResourceLocation id = BuiltInRegistries.BLOCK.getKey(block);
            BlockState state = block.defaultBlockState();

            JsonObject row = new JsonObject();
            row.addProperty("id", id.toString());
            row.addProperty("namespace", id.getNamespace());
            row.addProperty("path", id.getPath());
            row.addProperty("default_state", state.toString());

            JsonArray blockTags = tagsForBlock(block);
            row.add("block_tags", blockTags);
            if (!blockTags.isEmpty()) {
                blocksWithTags++;
            }

            Item item = block.asItem();
            boolean hasItem = item != Items.AIR;
            row.addProperty("has_item", hasItem);
            if (hasItem) {
                blocksWithItems++;
                ResourceLocation itemId = BuiltInRegistries.ITEM.getKey(item);
                row.addProperty("item_id", itemId.toString());
                row.addProperty("item_max_stack_size", item.getDefaultMaxStackSize());
                row.add("item_tags", tagsForItem(item));
            }

            row.addProperty("is_air", state.isAir());
            row.addProperty("light_emission", state.getLightEmission());
            row.addProperty("destroy_speed", safeDestroySpeed(state, level, probePos));
            row.addProperty("explosion_resistance", block.getExplosionResistance());
            row.addProperty("can_occlude", state.canOcclude());
            row.addProperty("replaceable", state.canBeReplaced());
            row.addProperty("collision_empty", safeCollisionEmpty(state, level, probePos));
            row.addProperty("has_fluid_state", !state.getFluidState().isEmpty());

            JsonArray properties = new JsonArray();
            for (Property<?> property : block.getStateDefinition().getProperties()) {
                JsonObject prop = new JsonObject();
                prop.addProperty("name", property.getName());
                JsonArray values = new JsonArray();
                for (Comparable<?> value : property.getPossibleValues()) {
                    values.add(value.toString());
                }
                prop.add("values", values);
                properties.add(prop);
            }
            row.add("state_properties", properties);

            boolean entityProvider = block instanceof EntityBlock;
            row.addProperty("block_entity_provider", entityProvider);
            if (entityProvider) {
                blockEntityProviders++;
                JsonObject beInfo = describeBlockEntity((EntityBlock) block, state);
                row.add("block_entity", beInfo);
            }

            blocks.add(row);
        }

        root.add("blocks", blocks);

        JsonArray items = new JsonArray();
        List<Item> sortedItems = new ArrayList<>();
        BuiltInRegistries.ITEM.forEach(sortedItems::add);
        sortedItems.sort(Comparator.comparing(item -> BuiltInRegistries.ITEM.getKey(item).toString()));

        for (Item item : sortedItems) {
            ResourceLocation id = BuiltInRegistries.ITEM.getKey(item);
            JsonObject row = new JsonObject();
            row.addProperty("id", id.toString());
            row.addProperty("namespace", id.getNamespace());
            row.addProperty("path", id.getPath());
            row.addProperty("max_stack_size", item.getDefaultMaxStackSize());
            row.add("tags", tagsForItem(item));
            items.add(row);
        }
        root.add("items", items);

        JsonObject summary = new JsonObject();
        summary.addProperty("block_count", blocks.size());
        summary.addProperty("item_count", items.size());
        summary.addProperty("block_entity_provider_count", blockEntityProviders);
        summary.addProperty("blocks_with_items", blocksWithItems);
        summary.addProperty("blocks_with_tags", blocksWithTags);
        root.add("summary", summary);

        Path outDir = Path.of("yan_recon");
        Files.createDirectories(outDir);
        Path output = outDir.resolve("runtime_registry_" + fileStamp + ".json").toAbsolutePath();
        Files.writeString(output, GSON.toJson(root), StandardCharsets.UTF_8);

        return new ExportResult(
                output,
                blocks.size(),
                items.size(),
                blockEntityProviders,
                blocksWithTags);
    }

    private static JsonArray exportMods() {
        JsonArray mods = new JsonArray();
        ModList.get().getMods().stream()
                .sorted(Comparator.comparing(mod -> mod.getModId()))
                .forEach(mod -> {
                    JsonObject row = new JsonObject();
                    row.addProperty("mod_id", mod.getModId());
                    row.addProperty("display_name", mod.getDisplayName());
                    row.addProperty("version", mod.getVersion().toString());
                    mods.add(row);
                });
        return mods;
    }

    private static JsonArray tagsForBlock(Block block) {
        JsonArray tags = new JsonArray();
        Holder<Block> holder = BuiltInRegistries.BLOCK.wrapAsHolder(block);
        holder.tags()
                .map(tag -> tag.location().toString())
                .sorted()
                .forEach(tags::add);
        return tags;
    }

    private static JsonArray tagsForItem(Item item) {
        JsonArray tags = new JsonArray();
        Holder<Item> holder = BuiltInRegistries.ITEM.wrapAsHolder(item);
        holder.tags()
                .map(tag -> tag.location().toString())
                .sorted()
                .forEach(tags::add);
        return tags;
    }

    private static JsonObject describeBlockEntity(EntityBlock block, BlockState state) {
        JsonObject result = new JsonObject();
        try {
            BlockEntity blockEntity = block.newBlockEntity(BlockPos.ZERO, state);
            if (blockEntity == null) {
                result.addProperty("instantiated", false);
                result.addProperty("class", "");
            } else {
                result.addProperty("instantiated", true);
                result.addProperty("class", blockEntity.getClass().getName());
                ResourceLocation typeId = BuiltInRegistries.BLOCK_ENTITY_TYPE.getKey(blockEntity.getType());
                if (typeId != null) {
                    result.addProperty("type_id", typeId.toString());
                }
            }
        } catch (Throwable error) {
            result.addProperty("instantiated", false);
            result.addProperty("error", error.getClass().getSimpleName() + ": " + String.valueOf(error.getMessage()));
        }
        return result;
    }

    private static float safeDestroySpeed(BlockState state, ServerLevel level, BlockPos pos) {
        try {
            return state.getDestroySpeed(level, pos);
        } catch (Throwable ignored) {
            return Float.NaN;
        }
    }

    private static boolean safeCollisionEmpty(BlockState state, ServerLevel level, BlockPos pos) {
        try {
            return state.getCollisionShape(level, pos).isEmpty();
        } catch (Throwable ignored) {
            return false;
        }
    }

    public record ExportResult(
            Path path,
            int blockCount,
            int itemCount,
            int blockEntityProviderCount,
            int blocksWithTags) {}
}
