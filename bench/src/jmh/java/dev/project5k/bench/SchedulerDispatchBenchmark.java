package dev.project5k.bench;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.infra.Blackhole;

/**
 * Cost of fanning one tick's work out to a worker pool and joining it, against
 * running the same work inline. Varies worker count and task granularity to find
 * the batch size where threading starts to pay for its dispatch/join overhead.
 */
@State(Scope.Benchmark)
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.MICROSECONDS)
public class SchedulerDispatchBenchmark {

    /** Total units of work per simulated tick. */
    @Param({"4096"})
    int workUnits;

    /** Work units per submitted task; small values expose dispatch overhead. */
    @Param({"1", "16", "256", "4096"})
    int batchSize;

    @Param({"1", "2", "3", "4", "6"})
    int workers;

    ExecutorService pool;

    @Setup(Level.Trial)
    public void setUp() {
        pool = Executors.newFixedThreadPool(workers);
    }

    @TearDown(Level.Trial)
    public void tearDown() throws InterruptedException {
        pool.shutdownNow();
        pool.awaitTermination(10, TimeUnit.SECONDS);
    }

    /** One work unit: a small, allocation-free computation, consumed so it can't be elided. */
    static long unit(long seed) {
        long x = seed * 0x9E3779B97F4A7C15L;
        for (int i = 0; i < 64; i++) {
            x ^= x >>> 31;
            x *= 0xBF58476D1CE4E5B9L;
        }
        return x;
    }

    @Benchmark
    public void sequential(Blackhole bh) {
        for (int i = 0; i < workUnits; i++) {
            bh.consume(unit(i));
        }
    }

    @Benchmark
    public void pooled(Blackhole bh) throws InterruptedException {
        int tasks = (workUnits + batchSize - 1) / batchSize;
        CountDownLatch done = new CountDownLatch(tasks);
        for (int t = 0; t < tasks; t++) {
            int start = t * batchSize;
            int end = Math.min(start + batchSize, workUnits);
            pool.execute(() -> {
                long acc = 0;
                for (int i = start; i < end; i++) {
                    acc += unit(i);
                }
                bh.consume(acc);
                done.countDown();
            });
        }
        done.await();
    }
}
