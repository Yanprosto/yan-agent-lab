package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanexperiment: deterministic autonomous build-test-rollback-mutate-retry loop. */
public final class YanExperimentCommand {
    private YanExperimentCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanexperiment")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanExperimentCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanexperiment must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startExperiment(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal(
                        "[yan-agent] Experiment v0.4 started at " + anchor.toShortString()
                                + ". Keep a 7x4x3 area EAST of you clear; the agent will build, test, rollback and retry."),
                false);
        return 1;
    }
}
