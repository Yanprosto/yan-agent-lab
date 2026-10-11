package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yansplitexperiment: live two-branch Mekanism topology search. */
public final class YanSplitterExperimentCommand {
    private YanSplitterExperimentCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yansplitexperiment")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanSplitterExperimentCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yansplitexperiment must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startSplitterExperiment(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal(
                        "[yan-agent] Splitter experiment v0.6 started at " + anchor.toShortString()
                                + ". Keep an 11x5x5 area EAST of you clear."),
                false);
        return 1;
    }
}
