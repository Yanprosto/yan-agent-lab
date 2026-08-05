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

/** Starts a semantic multi-component build with {@code /project <prompt>}. */
public final class ProjectCommand {
    private ProjectCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("project")
                        .requires(source -> source.hasPermission(0))
                        .then(Commands.argument("prompt", StringArgumentType.greedyString())
                                .executes(ProjectCommand::run)));
    }

    private static int run(com.mojang.brigadier.context.CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        ServerPlayer player;
        try {
            player = source.getPlayerOrException();
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException e) {
            source.sendFailure(Component.literal("[mcbuild-project] /project must be run by a player."));
            return 0;
        }
        ServerLevel level = source.getLevel();
        BlockPos anchor = player.blockPosition();
        String prompt = StringArgumentType.getString(ctx, "prompt");

        if (!BuildSessionManager.startProject(prompt, anchor, level, player)) {
            source.sendFailure(Component.literal("[mcbuild-project] A build is already in progress."));
            return 0;
        }
        source.sendSuccess(
                () -> Component.literal(
                        "[mcbuild-project] Planning \"" + prompt + "\" at " + anchor.toShortString() + "..."),
                false);
        return 1;
    }
}
