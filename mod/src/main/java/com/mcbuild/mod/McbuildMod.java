package com.mcbuild.mod;

import com.mcbuild.mod.command.BuildCommand;
import com.mcbuild.mod.command.ProjectCommand;
import com.mcbuild.mod.command.YanFunctionalCommand;
import com.mcbuild.mod.command.YanProbeCommand;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;

/** Mod entrypoint: wires live build commands and the YAN functional bridge into the server. */
@Mod(McbuildMod.MOD_ID)
public class McbuildMod {
    public static final String MOD_ID = "mcbuild_live";

    @EventBusSubscriber(modid = MOD_ID)
    public static class GameEvents {
        @SubscribeEvent
        public static void onRegisterCommands(RegisterCommandsEvent event) {
            BuildCommand.register(event.getDispatcher());
            ProjectCommand.register(event.getDispatcher());
            YanProbeCommand.register(event.getDispatcher());
            YanFunctionalCommand.register(event.getDispatcher());
        }

        @SubscribeEvent
        public static void onServerTick(ServerTickEvent.Post event) {
            BuildSessionManager.onServerTick(event.getServer());
        }
    }
}
