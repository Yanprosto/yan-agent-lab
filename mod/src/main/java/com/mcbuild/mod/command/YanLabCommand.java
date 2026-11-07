package com.mcbuild.mod.command;

import com.mcbuild.mod.BuildSessionManager;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.StringArgumentType;
import com.mojang.brigadier.context.CommandContext;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.commands.arguments.coordinates.BlockPosArgument;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerLevel;

/**
 * /yanlab &lt;experiment&gt; &lt;pos&gt;: start a YAN experiment at explicit coordinates without a player.
 *
 * <p>Meant for the server console, RCON and automated headless test runs. Experiments that need a
 * player's crosshair (probe, functional) are not offered here.
 */
public final class YanLabCommand {
    private YanLabCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanlab")
                        .requires(source -> source.hasPermission(2))
                        .then(Commands.argument("experiment", StringArgumentType.word())
                                .suggests((ctx, builder) -> {
                                    builder.suggest("experiment");
                                    builder.suggest("mekanism");
                                    builder.suggest("splitter");
                                    return builder.buildFuture();
                                })
                                .then(Commands.argument("pos", BlockPosArgument.blockPos())
                                        .executes(YanLabCommand::run))));
    }

    private static int run(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        CommandSourceStack source = ctx.getSource();
        String experiment = StringArgumentType.getString(ctx, "experiment");
        BlockPos anchor = BlockPosArgument.getLoadedBlockPos(ctx, "pos");
        ServerLevel level = source.getLevel();

        boolean started;
        switch (experiment) {
            case "experiment" -> started = BuildSessionManager.startExperiment(anchor, level, null);
            case "mekanism" -> started = BuildSessionManager.startMekanismExperiment(anchor, level, null);
            case "splitter" -> started = BuildSessionManager.startSplitterExperiment(anchor, level, null);
            default -> {
                source.sendFailure(Component.literal(
                        "[yan-lab] unknown experiment '" + experiment + "' (experiment|mekanism|splitter)"));
                return 0;
            }
        }
        if (!started) {
            source.sendFailure(Component.literal("[yan-lab] another mcbuild/YAN task is already in progress"));
            return 0;
        }
        source.sendSuccess(
                () -> Component.literal("[yan-lab] " + experiment + " started at " + anchor.toShortString()),
                true);
        return 1;
    }
}
