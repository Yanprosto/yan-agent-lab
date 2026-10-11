package com.mcbuild.mod.command;

import com.mcbuild.mod.recon.RuntimeRegistryExporter;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.context.CommandContext;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;

/** Writes an authoritative runtime block/item registry snapshot for the YAN lab. */
public final class YanRegistryDumpCommand {
    private YanRegistryDumpCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(
                Commands.literal("yanregistrydump")
                        .requires(source -> source.hasPermission(0))
                        .executes(YanRegistryDumpCommand::run));
    }

    private static int run(CommandContext<CommandSourceStack> ctx) {
        CommandSourceStack source = ctx.getSource();
        source.sendSuccess(
                () -> Component.literal("[yan-recon] exporting runtime block/item registry..."),
                false);

        try {
            RuntimeRegistryExporter.ExportResult result =
                    RuntimeRegistryExporter.export(source.getServer(), source.getLevel());

            source.sendSuccess(
                    () -> Component.literal(
                            "[yan-recon] PASS blocks="
                                    + result.blockCount()
                                    + " items="
                                    + result.itemCount()
                                    + " blockEntityProviders="
                                    + result.blockEntityProviderCount()
                                    + " taggedBlocks="
                                    + result.blocksWithTags()),
                    false);
            source.sendSuccess(
                    () -> Component.literal("[yan-recon] file: " + result.path()),
                    false);
            return 1;
        } catch (Exception error) {
            source.sendFailure(Component.literal(
                    "[yan-recon] FAIL "
                            + error.getClass().getSimpleName()
                            + ": "
                            + String.valueOf(error.getMessage())));
            return 0;
        }
    }
}
