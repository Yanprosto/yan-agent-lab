package com.mcbuild.mod;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mcbuild.mod.net.ProtocolMessages;
import com.mcbuild.mod.net.WsClient;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.neoforged.neoforge.server.ServerLifecycleHooks;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;

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

    public static final class Session {
        private final BlockPos anchor;
        private final ServerLevel level;
        private final ServerPlayer player;
        private final String chatPrefix;
        private WsClient client;

        private Session(String command, BlockPos anchor, ServerLevel level, ServerPlayer player) {
            this.anchor = anchor;
            this.level = level;
            this.player = player;
            this.chatPrefix = switch (command) {
                case "project" -> "[mcbuild-project]";
                case "probe" -> "[yan-agent]";
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
                JsonObject response = new JsonObject();
                response.addProperty("type", "observation");
                response.addProperty("id", request.id == null ? "" : request.id);
                try {
                    JsonObject result = new JsonObject();
                    if ("inspect_target".equals(request.action)) {
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
                        result.add("target", row);
                    } else if ("inspect_blocks".equals(request.action)) {
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
                        result.add("blocks", blocks);
                    } else {
                        throw new IllegalArgumentException("Unsupported action: " + request.action);
                    }
                    response.addProperty("ok", true);
                    response.add("result", result);
                } catch (Exception e) {
                    response.addProperty("ok", false);
                    response.addProperty("error", e.getClass().getSimpleName() + ": " + e.getMessage());
                }
                if (client != null && client.isOpen()) {
                    client.sendObservation(response);
                }
            });
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
