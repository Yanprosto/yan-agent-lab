package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanmission: autonomous production mission with no hand-built test fixture. */
public final class YanMissionCommand {
    private YanMissionCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanmission")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanMissionCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanmission must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startMission(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal(
                        "[yan-agent] Autonomous factory mission v2.0 started. No manual fixture required."),
                false);
        return 1;
    }
}
