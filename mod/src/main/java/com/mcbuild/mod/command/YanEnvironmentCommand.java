package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanenvironment: environment-aware build/repair loop over existing chests and obstacles. */
public final class YanEnvironmentCommand {
    private YanEnvironmentCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanenvironment")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanEnvironmentCommand::run));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanenvironment must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startEnvironmentBuild(anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal(
                        "[yan-agent] Environment builder v1.0 started at " + anchor.toShortString()
                                + ". Scene contract: exactly 3 chests nearby; one source contains 6 raw iron, two sinks are empty. Obstacles may remain in place."),
                false);
        return 1;
    }
}
