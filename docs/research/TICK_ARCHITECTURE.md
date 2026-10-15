# How Folia ticks, and whether work can be split by type — 2026-10-15

Source: pinned Folia `ver/26.1.x` (`62dc0f25`), patched sources under
`upstream/folia-26.1-baseline/folia-server/src/minecraft/java`, plus the Folia docs
(docs.papermc.io/folia/reference/overview, /region-logic). Read-only study; nothing built.

## 1. What Folia parallelises today

- **By area only.** Loaded chunks are grouped into region *sections* (2^gridExponent
  chunks square). Sections within the merge radius of each other must belong to the
  same region. Each region is one task on a shared tick-thread pool, scheduled
  earliest-deadline-first at 20 TPS (`TickRegionScheduler`, `TickRegions`).
- **One region = one thread.** A region's data (entities, chunks, block/fluid tick
  lists, tick counters) is only touched by the thread ticking it (`RegionizedWorldData`).
  Nothing inside a region runs in parallel.
- **Global region:** one 20 TPS task for game time, weather, world border, console.
- **Already off the tick threads:** chunk loading, generation and I/O (moonrise
  `MoonriseCommon.WORKER_POOL`, here 3 workers + 1 I/O thread), and network I/O and
  compression (Netty, 4 threads).
- **Thread count default:** `getTickThreads()` uses (cores / 2), and anything <= 4
  becomes **1 tick thread**. On the 6-core dev host the server logs "initial 1 target
  thread(s)". All runs so far, including the noise calibration in progress, used this
  default. A/B comparisons must set `threaded-regions.threads` explicitly and record it.

Consequence for this project: a dense city where players' view areas overlap becomes
**one region** (confirmed in our runs: 1 region, ~900–4,300 chunks). Folia then runs the
whole city on one thread, exactly like vanilla. That is the case to improve.

## 2. What one region tick does, in order

`TickRegions.tickRegion` → `MinecraftServer.tickServer(region)`:

1. Region task queue, player-connection packets queued for this region, region and
   entity schedulers (plugins, teleports).
2. `ServerLevel.tick(region)`:
   1. world border, time
   2. scheduled **block ticks**, then **fluid ticks** (redstone, crops, water...)
   3. raids
   4. **chunk source tick**: random ticks, natural mob spawning, broadcasting
      changed blocks, and the **entity tracker** (`ChunkMap.newTrackerTick`: for every
      entity, which nearby players see it; send movement/metadata updates)
   5. **block events** (pistons, note blocks, chests)
   6. **entity activation range**, then **entity ticks** (`forEachTickingEntity`): AI goals,
      pathfinding, movement with collision, item pickup, damage
   7. **block entity ticks** (hoppers, furnaces...)
3. Connection tick: process player input packets (movement, digging, placing, chat).

Folia's built-in profiler (`leafprofiler`) already times each phase separately
(BLOCK_TICK, FLUID_TICK, CHUNK_PROVIDER_TICK, ENTITY_TRACKER_TICK, ENTITY_TICK,
TILE_ENTITY, ...). We use it on the baseline to measure where crowd time goes,
before choosing what to change.

## 3. The proposal: threads per workload instead of per area

> "Rather than assigning one thread to every group of chunks, we could assign different
> threads to entities, physics calculations, player interactions, and other workloads,
> while maintaining a consistent world state."

### Why a straight functional split breaks vanilla behaviour

Every phase above reads **and writes** the same world state: block states, entity
positions, inventories. Vanilla's results depend on the strict order *within* a tick:
- an entity sees the positions of entities that ticked before it
- a block a player placed this tick is visible to the mob that paths after it
- redstone update order decides circuit outcomes
- two players racing for one item: whoever ticks first gets it

If entities, physics and player actions run on separate threads against the same state at
the same time, we must either:
- **lock** shared data: contention in exactly the dense case, deadlock risk, and
  nondeterministic order (different results run to run); or
- **double-buffer** (everyone reads last tick's snapshot, writes are merged at the end):
  removes the in-tick ordering above, so it is a visible gameplay change (e.g. two mobs
  both "win" the same spot, items duplicated or lost), and needs conflict rules for
  every kind of write.

It also scales poorly: there are only ~4–6 workload types and they are very unequal
(entity ticking usually dominates), so the speedup is capped by the largest phase.

### The version that can work: owner thread commits, helpers compute

Keep one owner thread per region that applies every **mutation** in vanilla order, and
move **read-mostly computation** to helper threads, in parallel with or ahead of the
owner. This is the spec's CPU track (§2.1). Candidates, roughly by expected safety:

| Candidate | Why it parallelises | Semantics risk |
|---|---|---|
| Entity tracker visibility (`newTrackerTick`) | per-entity "which players see it" only reads positions; packet building is independent | low: output is packets, not world state |
| Collision broad-phase candidate gathering | reads block shapes and entity boxes; the owner does the final resolution | low if candidates are re-validated on commit |
| Pathfinding (A* search) | pure search over a block snapshot | medium: results land a tick later unless computed ahead; must revalidate against changes |
| Mob AI goal *evaluation* (target selection, sensing) | mostly reads | medium: some goals mutate as they evaluate |
| Spatial sub-partitioning of a dense region | entities that cannot affect each other this tick tick in parallel, merged in a deterministic order | high: needs a proven independence rule; this is the research frontier |

Prior art to review before implementing (not yet verified for 26.x): Paper forks such
as Pufferfish, Petal and Leaf ship "async pathfinding" and "async/multithreaded entity
tracker" options; C2ME parallelises chunk generation (already off-thread in Folia).

### Answer

Splitting purely by workload type over one shared, consistent world state is **not
possible without either locks or giving up vanilla's in-tick ordering**. The workable
form is a **hybrid**: keep Folia's area split, and inside a crowded region keep one owner
thread for all writes, while helper threads compute read-only work (tracking,
collision candidates, pathfinding) in parallel, with every result re-checked when it is
applied. That keeps world state consistent and is measurable piece by piece.

## 4. Next steps (after the noise calibration finishes)

1. Profile the `crowd50` baseline with Folia's profiler: per-phase share of tick time.
2. Pick the first candidate from the table using that data (expected: entity tracker or
   collision candidates), write its correctness tests first, then implement it in the
   fork, never in the baseline checkout.
3. A/B against Folia with an explicit, equal `threaded-regions.threads` setting.
