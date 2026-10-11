package com.mcbuild.mod;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mcbuild.mod.net.ProtocolMessages;
import com.mcbuild.mod.net.WsClient;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.neoforge.energy.IEnergyStorage;
import net.neoforged.neoforge.items.IItemHandler;
import net.neoforged.neoforge.server.ServerLifecycleHooks;

/** Tracks the single in-flight live session and owns all world-thread interaction. */
public final class BuildSessionManager {
    private static Session active;

    private BuildSessionManager() {}

    public static synchronized boolean startBuild(String prompt, BlockPos anchor, ServerLevel level, ServerPlayer player) {
        return start("build", prompt, anchor, level, player);
    }

    public static synchronized boolean startProject(
            String prompt, BlockPos anchor, ServerLevel level, ServerPlayer player) {
        return start("project", prompt, anchor, level, player);
    }

    public static synchronized boolean startProbe(BlockPos anchor, ServerLevel level, ServerPlayer player) {
        return start("probe", "", anchor, level, player);
    }

    public static synchronized boolean startFunctional(BlockPos anchor, ServerLevel level, ServerPlayer player) {
        return start("functional", "", anchor, level, player);
    }

    public static synchronized boolean startExperiment(BlockPos anchor, ServerLevel level, ServerPlayer player) {
        return start("experiment", "", anchor, level, player);
    }

    private static synchronized boolean start(
            String command, String prompt, BlockPos anchor, ServerLevel level, ServerPlayer player) {
        if (active != null) {
            return false;
        }
        Session session = new Session(command, anchor, level, player);
        active = session;
        WsClient client = new WsClient(command, prompt, session);
        session.client = client;
        client.connect();
        return true;
    }

    private static synchronized void clear(Session session) {
        if (active == session) {
            active = null;
        }
    }

    /** Called once per real server tick from the NeoForge tick event. */
    public static void onServerTick(MinecraftServer server) {
        Session session;
        synchronized (BuildSessionManager.class) {
            session = active;
        }
        if (session != null) {
            session.onServerTick(server.getTickCount());
        }
    }

    public static final class Session {
        private final BlockPos anchor;
        private final ServerLevel level;
        private final ServerPlayer player;
        private final String chatPrefix;
        private final Set<BlockPos> agentPlaced = new HashSet<>();
        private WsClient client;

        private String pendingWaitId;
        private int pendingWaitStartedTick;
        private int pendingWaitUntilTick;
        private int pendingWaitRequestedTicks;

        private Session(String command, BlockPos anchor, ServerLevel level, ServerPlayer player) {
            this.anchor = anchor;
            this.level = level;
            this.player = player;
            this.chatPrefix = switch (command) {
                case "project" -> "[mcbuild-project]";
                case "probe", "functional", "experiment" -> "[yan-agent]";
                default -> "[mcbuild]";
            };
        }

        public void onChat(String text) {
            runOnServerThread(() -> player.sendSystemMessage(Component.literal(text)));
        }

        public void onBlocks(ProtocolMessages.Blocks blocks) {
            runOnServerThread(() -> {
                for (ProtocolMessages.BlockChange change : blocks.changes) {
                    BlockPos pos = anchor.offset(change.x, change.y, change.z);
                    BlockState state;
                    if (change.block == null) {
                        state = Blocks.AIR.defaultBlockState();
                    } else {
                        try {
                            state = BlockStateCodec.parse(level.registryAccess(), change.block);
                        } catch (CommandSyntaxException e) {
                            player.sendSystemMessage(Component.literal(
                                    chatPrefix + " failed to parse block '" + change.block + "': " + e.getMessage()));
                            continue;
                        }
                    }
                    level.setBlock(pos, state, 3);
                }
            });
        }

        /** Execute a server-requested tool action against the real world and send observation back. */
        public void onAction(ProtocolMessages.Action request) {
            runOnServerThread(() -> {
                try {
                    if ("wait_ticks".equals(request.action)) {
                        beginWait(request);
                        return;
                    }

                    JsonObject result = switch (request.action) {
                        case "inspect_target" -> inspectTarget(request);
                        case "inspect_blocks" -> inspectBlocks(request);
                        case "read_inventory" -> readInventory(request);
                        case "read_energy" -> readEnergy(request);
                        case "seed_item" -> seedItem(request);
                        case "drain_inventory" -> drainInventory(request);
                        case "place_block" -> placeBlock(request);
                        case "remove_block" -> removeBlock(request);
                        case "rollback_session" -> rollbackSession();
                        default -> throw new IllegalArgumentException("Unsupported action: " + request.action);
                    };
                    sendObservation(request.id, true, result, null);
                } catch (Exception e) {
                    sendObservation(
                            request.id,
                            false,
                            null,
                            e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()));
                }
            });
        }

        private JsonObject inspectTarget(ProtocolMessages.Action request) {
            double reach = 12.0D;
            if (request.args != null && request.args.has("reach")) {
                reach = Math.max(1.0D, Math.min(64.0D, request.args.get("reach").getAsDouble()));
            }
            Vec3 start = player.getEyePosition();
            Vec3 end = start.add(player.getLookAngle().scale(reach));
            BlockHitResult hit = level.clip(new ClipContext(
                    start, end, ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, player));
            if (hit.getType() != HitResult.Type.BLOCK) {
                throw new IllegalStateException("No block under crosshair within " + reach + " blocks");
            }
            BlockPos pos = hit.getBlockPos();
            JsonObject row = describeBlock(pos, pos.subtract(anchor));
            row.addProperty("hit_face", hit.getDirection().getName());
            JsonObject result = new JsonObject();
            result.add("target", row);
            return result;
        }

        private JsonObject inspectBlocks(ProtocolMessages.Action request) {
            JsonArray positions = request.args == null ? null : request.args.getAsJsonArray("positions");
            if (positions == null) {
                throw new IllegalArgumentException("inspect_blocks requires args.positions");
            }
            JsonArray blocks = new JsonArray();
            for (JsonElement element : positions) {
                JsonObject rel = element.getAsJsonObject();
                int x = rel.get("x").getAsInt();
                int y = rel.get("y").getAsInt();
                int z = rel.get("z").getAsInt();
                BlockPos pos = anchor.offset(x, y, z);
                blocks.add(describeBlock(pos, new BlockPos(x, y, z)));
            }
            JsonObject result = new JsonObject();
            result.add("blocks", blocks);
            return result;
        }

        private JsonObject readInventory(ProtocolMessages.Action request) {
            BlockPos pos = resolveRelativePos(request.args);
            Direction side = parseOptionalSide(request.args);
            IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, side);

            JsonObject result = baseLocationResult(pos);
            result.addProperty("side", side == null ? "unsided" : side.getName());
            if (handler == null) {
                result.addProperty("available", false);
                result.addProperty("slots", 0);
                result.addProperty("total_items", 0);
                result.add("items", new JsonArray());
                return result;
            }

            result.addProperty("available", true);
            result.addProperty("slots", handler.getSlots());
            int total = 0;
            JsonArray items = new JsonArray();
            for (int slot = 0; slot < handler.getSlots(); slot++) {
                ItemStack stack = handler.getStackInSlot(slot);
                if (stack.isEmpty()) {
                    continue;
                }
                total += stack.getCount();
                JsonObject row = new JsonObject();
                row.addProperty("slot", slot);
                row.addProperty("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
                row.addProperty("count", stack.getCount());
                items.add(row);
            }
            result.addProperty("total_items", total);
            result.add("items", items);
            return result;
        }

        private JsonObject seedItem(ProtocolMessages.Action request) {
            BlockPos pos = resolveRelativePos(request.args);
            Direction side = parseOptionalSide(request.args);
            if (request.args == null || !request.args.has("item")) {
                throw new IllegalArgumentException("seed_item requires args.item");
            }
            int count = request.args.has("count") ? request.args.get("count").getAsInt() : 1;
            count = Math.max(1, Math.min(4096, count));

            ResourceLocation itemId = ResourceLocation.tryParse(request.args.get("item").getAsString());
            if (itemId == null) {
                throw new IllegalArgumentException("Invalid item id: " + request.args.get("item").getAsString());
            }
            Item item = BuiltInRegistries.ITEM.getOptional(itemId)
                    .orElseThrow(() -> new IllegalArgumentException("Unknown item: " + itemId));

            IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, side);
            if (handler == null) {
                throw new IllegalStateException("No item handler at " + pos.toShortString());
            }

            int remainingCount = count;
            int inserted = 0;
            while (remainingCount > 0) {
                int batch = Math.min(remainingCount, item.getDefaultMaxStackSize());
                ItemStack remainder = new ItemStack(item, batch);
                for (int slot = 0; slot < handler.getSlots() && !remainder.isEmpty(); slot++) {
                    remainder = handler.insertItem(slot, remainder, false);
                }
                int accepted = batch - remainder.getCount();
                inserted += accepted;
                remainingCount -= accepted;
                if (accepted == 0) {
                    break;
                }
            }

            JsonObject result = baseLocationResult(pos);
            result.addProperty("item", itemId.toString());
            result.addProperty("requested", count);
            result.addProperty("inserted", inserted);
            result.addProperty("remaining", count - inserted);
            if (inserted != count) {
                throw new IllegalStateException("seed_item inserted only " + inserted + "/" + count);
            }
            return result;
        }

        private JsonObject drainInventory(ProtocolMessages.Action request) {
            BlockPos pos = resolveRelativePos(request.args);
            Direction side = parseOptionalSide(request.args);
            ResourceLocation filter = null;
            if (request.args != null && request.args.has("item") && !request.args.get("item").isJsonNull()) {
                filter = ResourceLocation.tryParse(request.args.get("item").getAsString());
                if (filter == null) {
                    throw new IllegalArgumentException("Invalid item id filter");
                }
            }

            IItemHandler handler = level.getCapability(Capabilities.ItemHandler.BLOCK, pos, side);
            if (handler == null) {
                throw new IllegalStateException("No item handler at " + pos.toShortString());
            }

            int removed = 0;
            JsonArray removedItems = new JsonArray();
            for (int slot = 0; slot < handler.getSlots(); slot++) {
                while (true) {
                    ItemStack stack = handler.getStackInSlot(slot);
                    if (stack.isEmpty()) {
                        break;
                    }
                    ResourceLocation id = BuiltInRegistries.ITEM.getKey(stack.getItem());
                    if (filter != null && !filter.equals(id)) {
                        break;
                    }
                    ItemStack extracted = handler.extractItem(slot, Math.min(stack.getCount(), stack.getMaxStackSize()), false);
                    if (extracted.isEmpty()) {
                        break;
                    }
                    removed += extracted.getCount();
                    JsonObject row = new JsonObject();
                    row.addProperty("slot", slot);
                    row.addProperty("item", BuiltInRegistries.ITEM.getKey(extracted.getItem()).toString());
                    row.addProperty("count", extracted.getCount());
                    removedItems.add(row);
                }
            }

            JsonObject result = baseLocationResult(pos);
            result.addProperty("removed_total", removed);
            result.add("removed_items", removedItems);
            return result;
        }

        private JsonObject rollbackSession() {
            List<BlockPos> positions = new ArrayList<>(agentPlaced);
            int removed = 0;
            int alreadyAir = 0;
            for (BlockPos pos : positions) {
                if (level.getBlockState(pos).isAir()) {
                    alreadyAir++;
                    agentPlaced.remove(pos);
                    continue;
                }
                if (level.setBlock(pos, Blocks.AIR.defaultBlockState(), 3)) {
                    removed++;
                    agentPlaced.remove(pos);
                }
            }

            JsonObject result = new JsonObject();
            result.addProperty("tracked_before", positions.size());
            result.addProperty("removed", removed);
            result.addProperty("already_air", alreadyAir);
            result.addProperty("tracked_after", agentPlaced.size());
            return result;
        }

        private JsonObject readEnergy(ProtocolMessages.Action request) {
            BlockPos pos = resolveRelativePos(request.args);
            Direction side = parseOptionalSide(request.args);
            IEnergyStorage storage = level.getCapability(Capabilities.EnergyStorage.BLOCK, pos, side);

            JsonObject result = baseLocationResult(pos);
            result.addProperty("side", side == null ? "unsided" : side.getName());
            if (storage == null) {
                result.addProperty("available", false);
                result.addProperty("energy", 0);
                result.addProperty("capacity", 0);
                result.addProperty("can_extract", false);
                result.addProperty("can_receive", false);
                return result;
            }

            result.addProperty("available", true);
            result.addProperty("energy", storage.getEnergyStored());
            result.addProperty("capacity", storage.getMaxEnergyStored());
            result.addProperty("can_extract", storage.canExtract());
            result.addProperty("can_receive", storage.canReceive());
            return result;
        }

        private JsonObject placeBlock(ProtocolMessages.Action request) throws CommandSyntaxException {
            BlockPos pos = resolveRelativePos(request.args);
            if (request.args == null || !request.args.has("block")) {
                throw new IllegalArgumentException("place_block requires args.block");
            }
            String blockText = request.args.get("block").getAsString();
            BlockState before = level.getBlockState(pos);
            if (!before.isAir()) {
                throw new IllegalStateException(
                        "Refusing to overwrite non-air block at " + pos.toShortString() + ": "
                                + BuiltInRegistries.BLOCK.getKey(before.getBlock()));
            }

            BlockState state = BlockStateCodec.parse(level.registryAccess(), blockText);
            if (state.isAir()) {
                throw new IllegalArgumentException("place_block cannot place air; use remove_block");
            }
            if (!level.setBlock(pos, state, 3)) {
                throw new IllegalStateException("level.setBlock returned false at " + pos.toShortString());
            }
            agentPlaced.add(pos.immutable());

            JsonObject result = baseLocationResult(pos);
            result.addProperty("placed", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
            result.addProperty("tracked_for_rollback", true);
            return result;
        }

        private JsonObject removeBlock(ProtocolMessages.Action request) {
            BlockPos pos = resolveRelativePos(request.args);
            if (!agentPlaced.contains(pos)) {
                throw new IllegalStateException(
                        "Refusing to remove block not placed by this agent session at " + pos.toShortString());
            }
            BlockState before = level.getBlockState(pos);
            if (!level.setBlock(pos, Blocks.AIR.defaultBlockState(), 3)) {
                throw new IllegalStateException("level.setBlock returned false while removing " + pos.toShortString());
            }
            agentPlaced.remove(pos);

            JsonObject result = baseLocationResult(pos);
            result.addProperty("removed", BuiltInRegistries.BLOCK.getKey(before.getBlock()).toString());
            result.addProperty("is_air", level.getBlockState(pos).isAir());
            return result;
        }

        private void beginWait(ProtocolMessages.Action request) {
            if (pendingWaitId != null) {
                throw new IllegalStateException("A wait_ticks action is already pending");
            }
            int ticks = request.args != null && request.args.has("ticks")
                    ? request.args.get("ticks").getAsInt()
                    : 1;
            ticks = Math.max(1, Math.min(20 * 60 * 10, ticks));

            MinecraftServer server = ServerLifecycleHooks.getCurrentServer();
            if (server == null) {
                throw new IllegalStateException("Minecraft server is unavailable");
            }
            pendingWaitId = request.id == null ? "" : request.id;
            pendingWaitStartedTick = server.getTickCount();
            pendingWaitRequestedTicks = ticks;
            pendingWaitUntilTick = pendingWaitStartedTick + ticks;
        }

        private void onServerTick(int currentTick) {
            if (pendingWaitId == null || currentTick < pendingWaitUntilTick) {
                return;
            }
            String requestId = pendingWaitId;
            int started = pendingWaitStartedTick;
            int requested = pendingWaitRequestedTicks;
            pendingWaitId = null;

            JsonObject result = new JsonObject();
            result.addProperty("requested_ticks", requested);
            result.addProperty("start_tick", started);
            result.addProperty("end_tick", currentTick);
            result.addProperty("elapsed_ticks", currentTick - started);
            sendObservation(requestId, true, result, null);
        }

        private BlockPos resolveRelativePos(JsonObject args) {
            if (args == null || !args.has("x") || !args.has("y") || !args.has("z")) {
                throw new IllegalArgumentException("action requires relative args.x, args.y, args.z");
            }
            return anchor.offset(args.get("x").getAsInt(), args.get("y").getAsInt(), args.get("z").getAsInt());
        }

        private Direction parseOptionalSide(JsonObject args) {
            if (args == null || !args.has("side") || args.get("side").isJsonNull()) {
                return null;
            }
            String name = args.get("side").getAsString();
            Direction side = Direction.byName(name);
            if (side == null) {
                throw new IllegalArgumentException("Unknown side: " + name);
            }
            return side;
        }

        private JsonObject baseLocationResult(BlockPos pos) {
            JsonObject result = new JsonObject();
            BlockPos rel = pos.subtract(anchor);
            result.addProperty("x", rel.getX());
            result.addProperty("y", rel.getY());
            result.addProperty("z", rel.getZ());
            result.addProperty("world_x", pos.getX());
            result.addProperty("world_y", pos.getY());
            result.addProperty("world_z", pos.getZ());
            result.addProperty("block", BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos).getBlock()).toString());
            return result;
        }

        private void sendObservation(String requestId, boolean ok, JsonObject result, String error) {
            JsonObject response = new JsonObject();
            response.addProperty("type", "observation");
            response.addProperty("id", requestId == null ? "" : requestId);
            response.addProperty("ok", ok);
            if (result != null) {
                response.add("result", result);
            }
            if (error != null) {
                response.addProperty("error", error);
            }
            if (client != null && client.isOpen()) {
                client.sendObservation(response);
            }
        }

        private JsonObject describeBlock(BlockPos pos, BlockPos rel) {
            BlockState state = level.getBlockState(pos);
            BlockEntity be = level.getBlockEntity(pos);
            JsonObject row = new JsonObject();
            row.addProperty("x", rel.getX());
            row.addProperty("y", rel.getY());
            row.addProperty("z", rel.getZ());
            row.addProperty("world_x", pos.getX());
            row.addProperty("world_y", pos.getY());
            row.addProperty("world_z", pos.getZ());
            row.addProperty("block", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
            row.addProperty("state", state.toString());
            row.addProperty("is_air", state.isAir());
            if (be != null) {
                row.addProperty("block_entity", be.getClass().getName());
            }
            return row;
        }

        public void onFinish(String summary) {
            runOnServerThread(() -> player.sendSystemMessage(Component.literal(chatPrefix + " " + summary)));
            clear(this);
        }

        public void onError(String reason) {
            runOnServerThread(() -> player.sendSystemMessage(Component.literal(chatPrefix + " error: " + reason)));
            clear(this);
        }

        public void onClose() {
            clear(this);
        }

        private void runOnServerThread(Runnable task) {
            MinecraftServer server = ServerLifecycleHooks.getCurrentServer();
            if (server != null) {
                server.execute(task);
            }
        }
    }
}
