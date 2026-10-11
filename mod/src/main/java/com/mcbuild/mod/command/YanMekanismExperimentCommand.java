package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanmekexperiment: live Mekanism config mutation experiment. */
public final class YanMekanismExperimentCommand {
    private YanMekanismExperimentCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanmekexperiment")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanMekanismExperimentCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanmekexperiment must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startMekanismExperiment(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal(
                        "[yan-agent] Mekanism experiment v0.5 started at " + anchor.toShortString()
                                + ". Keep a 5x5x3 area EAST of you clear."),
                false);
        return 1;
    }
}
