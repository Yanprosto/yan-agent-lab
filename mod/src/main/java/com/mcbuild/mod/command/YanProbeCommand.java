package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanprobe: minimal bidirectional Python <-> live-world observation test. */
public final class YanProbeCommand {
    private YanProbeCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanprobe")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanProbeCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanprobe must be run by a player."));
            return 0;
        }
        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startProbe(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild task is already in progress."));
            return 0;
        }
        source.sendSuccess(() -> Component.literal("[yan-agent] Probe started at " + anchor.toShortString()), false);
        return 1;
    }
}
