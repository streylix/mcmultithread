package dev.project5k.telemetry;

import ca.spottedleaf.moonrise.common.time.TickData;
import ca.spottedleaf.moonrise.common.time.TickTime;
import io.papermc.paper.threadedregions.RegionizedServer;
import io.papermc.paper.threadedregions.ThreadedRegionizer;
import io.papermc.paper.threadedregions.TickRegionScheduler;
import io.papermc.paper.threadedregions.TickRegions;
import java.io.BufferedWriter;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.ChunkPos;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Copies every completed region tick out of Folia's 5-second tick windows, once per
 * second, on a dedicated low-priority thread. Region threads are only touched for the
 * brief lock Folia itself uses to append tick times. Read-only: no game state changes.
 *
 * Output (plugins/TickTelemetry/):
 *   ticks.csv   region,world,scheduled_start_ns,tick_start_ns,tick_end_ns,cpu_ns,intermediate_ns
 *   regions.csv wall_ms,nano,region,world,center_chunk_x,center_chunk_z,chunks,players,entities
 * Region -1 is the global tick. Both files share System.nanoTime(); regions.csv pairs it
 * with wall-clock milliseconds every second so ticks can be aligned with recordings.
 */
public final class TickTelemetry extends JavaPlugin {

    private static final long SAMPLE_INTERVAL_MS = 1000L;

    private volatile boolean running;
    private Thread sampler;
    private Field tickTimesField;
    private Field timeDataField;
    private final Map<Long, Long> lastTickStart = new HashMap<>();

    @Override
    public void onEnable() {
        try {
            this.tickTimesField = TickRegionScheduler.RegionScheduleHandle.class.getDeclaredField("tickTimes5s");
            this.tickTimesField.setAccessible(true);
            this.timeDataField = TickData.class.getDeclaredField("timeData");
            this.timeDataField.setAccessible(true);
            Files.createDirectories(this.getDataFolder().toPath());
        } catch (final ReflectiveOperationException | IOException ex) {
            throw new IllegalStateException("TickTelemetry cannot attach to Folia tick data", ex);
        }
        this.running = true;
        this.sampler = new Thread(this::run, "TickTelemetry");
        this.sampler.setDaemon(true);
        this.sampler.setPriority(Thread.MIN_PRIORITY);
        this.sampler.start();
    }

    @Override
    public void onDisable() {
        this.running = false;
        if (this.sampler != null) {
            this.sampler.interrupt();
            try {
                this.sampler.join(5000L);
            } catch (final InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private void run() {
        final Path dir = this.getDataFolder().toPath();
        try (BufferedWriter ticks = Files.newBufferedWriter(dir.resolve("ticks.csv"));
             BufferedWriter regions = Files.newBufferedWriter(dir.resolve("regions.csv"))) {
            ticks.write("region,world,scheduled_start_ns,tick_start_ns,tick_end_ns,cpu_ns,intermediate_ns\n");
            regions.write("wall_ms,nano,region,world,center_chunk_x,center_chunk_z,chunks,players,entities\n");
            while (this.running) {
                this.sample(ticks, regions);
                ticks.flush();
                regions.flush();
                try {
                    Thread.sleep(SAMPLE_INTERVAL_MS);
                } catch (final InterruptedException ignored) {
                    // final sample below
                }
            }
            this.sample(ticks, regions);
        } catch (final IOException ex) {
            this.getLogger().severe("TickTelemetry stopped: " + ex);
        }
    }

    private void sample(final BufferedWriter ticks, final BufferedWriter regions) throws IOException {
        final long wall = System.currentTimeMillis();
        final long nano = System.nanoTime();
        this.drain(-1L, "global", RegionizedServer.getGlobalTickData(), ticks);
        regions.write(wall + "," + nano + ",-1,global,,,,,\n");

        for (final ServerLevel level : MinecraftServer.getServer().getAllLevels()) {
            final String world = level.dimension().identifier().toString();
            final List<ThreadedRegionizer.ThreadedRegion<TickRegions.TickRegionData, TickRegions.TickRegionSectionData>> list = new ArrayList<>();
            level.regioniser.computeForAllRegions(list::add);
            for (final var region : list) {
                final TickRegions.TickRegionData data = region.getData();
                this.drain(region.id, world, data.getRegionSchedulingHandle(), ticks);
                final TickRegions.RegionStats stats = data.getRegionStats();
                final ChunkPos center = region.getCenterChunk();
                regions.write(wall + "," + nano + "," + region.id + "," + world + ","
                    + (center == null ? "" : center.x()) + "," + (center == null ? "" : center.z()) + ","
                    + stats.getChunkCount() + "," + stats.getPlayerCount() + "," + stats.getEntityCount() + "\n");
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void drain(final long regionId, final String world, final TickRegionScheduler.RegionScheduleHandle handle,
                       final BufferedWriter out) throws IOException {
        final TickTime[] snapshot;
        try {
            final TickData data = (TickData) this.tickTimesField.get(handle);
            // Folia appends under the handle's monitor (RegionScheduleHandle#addTickTime).
            synchronized (handle) {
                snapshot = ((ArrayDeque<TickTime>) this.timeDataField.get(data)).toArray(new TickTime[0]);
            }
        } catch (final IllegalAccessException ex) {
            throw new IllegalStateException(ex);
        }
        final long last = this.lastTickStart.getOrDefault(regionId, Long.MIN_VALUE);
        long newest = last;
        for (final TickTime t : snapshot) {
            if (t.tickStart() <= last) {
                continue;
            }
            out.write(regionId + "," + world + "," + t.scheduledTickStart() + "," + t.tickStart() + ","
                + t.tickEnd() + "," + (t.supportCPUTime() ? t.tickEndCPU() - t.tickStartCPU() : -1L) + ","
                + t.intermediateTaskExecutionTime() + "\n");
            newest = Math.max(newest, t.tickStart());
        }
        this.lastTickStart.put(regionId, newest);
    }
}
