package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;

/** /yanindustry <goal>: goal-driven industrial process mission. */
public final class YanIndustryCommand {
    private YanIndustryCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanindustry")
                        .requires(source -> source.hasPermission(0))
                        .then(Commands.argument("goal", StringArgumentType.greedyString())
                                .executes(YanIndustryCommand::run))
                        .executes(YanIndustryCommand::runDefault));
    }

    private static int runDefault(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        return start(ctx.getSource(), "переработка железа");
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        return start(ctx.getSource(), StringArgumentType.getString(ctx, "goal"));
    }

    private static int start(CommandSourceStack source, String goal) {
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[yan-agent] /yanindustry must be run by a player."));
            return 0;
        }

        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        if (!BuildSessionManager.startIndustry(goal, anchor, level, player)) {
            source.sendFailure(Component.literal("[yan-agent] Another mcbuild/YAN task is already in progress."));
            return 0;
        }

        source.sendSuccess(
                () -> Component.literal("[yan-agent] Goal-driven industrial mission started: " + goal),
                false);
        return 1;
    }
}
