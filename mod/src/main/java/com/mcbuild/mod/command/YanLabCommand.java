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
                        .then(Commands.literal("plan")
                                .then(Commands.argument("pos", BlockPosArgument.blockPos())
                                        .then(Commands.argument("spec", StringArgumentType.greedyString())
                                                .executes(YanLabCommand::runPlan))))
                        .then(Commands.literal("machine")
                                .then(Commands.argument("pos", BlockPosArgument.blockPos())
                                        .then(Commands.argument("spec", StringArgumentType.greedyString())
                                                .executes(YanLabCommand::runMachineProbe))))
                        .then(Commands.literal("industry")
                                .then(Commands.argument("pos", BlockPosArgument.blockPos())
                                        .then(Commands.argument("goal", StringArgumentType.greedyString())
                                                .executes(YanLabCommand::runIndustry))))
                        .then(Commands.argument("experiment", StringArgumentType.word())
                                .suggests((ctx, builder) -> {
                                    builder.suggest("experiment");
                                    builder.suggest("mekanism");
                                    builder.suggest("splitter");
                                    builder.suggest("environment");
                                    builder.suggest("mission");
                                    builder.suggest("industry");
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
            case "environment" -> started = BuildSessionManager.startEnvironmentBuild(anchor, level, null);
            case "mission" -> started = BuildSessionManager.startMission(anchor, level, null);
            default -> {
                source.sendFailure(Component.literal(
                        "[yan-lab] unknown experiment '" + experiment
                                + "' (experiment|mekanism|splitter|environment|mission; industry <pos> <goal>; machine <pos> <id>)"));
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

    private static int runPlan(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        CommandSourceStack source = ctx.getSource();
        BlockPos anchor = BlockPosArgument.getLoadedBlockPos(ctx, "pos");
        String spec = StringArgumentType.getString(ctx, "spec");
        if (!BuildSessionManager.startPlan(spec, anchor, source.getLevel(), null)) {
            source.sendFailure(Component.literal("[yan-lab] another mcbuild/YAN task is already in progress"));
            return 0;
        }
        source.sendSuccess(
                () -> Component.literal("[yan-lab] plan '" + spec + "' started at " + anchor.toShortString()), true);
        return 1;
    }

    private static int runMachineProbe(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        CommandSourceStack source = ctx.getSource();
        BlockPos anchor = BlockPosArgument.getLoadedBlockPos(ctx, "pos");
        String spec = StringArgumentType.getString(ctx, "spec");
        if (!BuildSessionManager.startMachineProbe(spec, anchor, source.getLevel(), null)) {
            source.sendFailure(Component.literal("[yan-lab] another mcbuild/YAN task is already in progress"));
            return 0;
        }
        source.sendSuccess(
                () -> Component.literal("[yan-lab] machine probe '" + spec + "' started at " + anchor.toShortString()),
                true);
        return 1;
    }

    private static int runIndustry(CommandContext<CommandSourceStack> ctx) throws CommandSyntaxException {
        CommandSourceStack source = ctx.getSource();
        BlockPos anchor = BlockPosArgument.getLoadedBlockPos(ctx, "pos");
        String goal = StringArgumentType.getString(ctx, "goal");
        if (!BuildSessionManager.startIndustry(goal, anchor, source.getLevel(), null)) {
            source.sendFailure(Component.literal("[yan-lab] another mcbuild/YAN task is already in progress"));
            return 0;
        }
        source.sendSuccess(
                () -> Component.literal("[yan-lab] industry '" + goal + "' started at " + anchor.toShortString()),
                true);
        return 1;
    }
}
