# Large-scale netcode: PlanetSide 2 and Unreal/Fortnite — 2026-10-15

What games with many players in one space do, and what applies to a server-side-only
Minecraft change (unmodified clients; deviation tiers in PROJECT_SPEC.md §1).

## PlanetSide 2 (ForgeLight engine)

Public technical detail is thin. No official server-architecture talk or write-up was
found, so the points below are graded by source quality.

- **Scale (documented):** ForgeLight targets "up to 2,000 [players] on a single game
  server"; one continent (zone) is a continuous world without loading screens; clients
  render "over 200 players at once" ([Wikipedia: ForgeLight][fl]). Players report the
  per-continent cap later dropped toward ~1,200 "for performance" (forum claims, unverified)
  ([Steam][s1]); a 1,158-player single battle is the commonly cited record ([Steam][s1]).
- **Hit detection (community/fan-site, unverified):** hybrid: the client handles physics
  and reports hits; the server rewinds the target to the shooter's estimated time and
  validates ([PlanetSide Universe][psu]). Server CPU is saved by trusting clients more.
- **Server work (documented, Daybreak patch notes):** recent optimisation was mostly
  targeted: e.g. interactive NPCs (terminals) changed from querying every character in
  range to only those actually interacting ([MassivelyOP 2023][mop23]); added "profiling
  zones" for server telemetry ([PTS notes][pts]); hardware upgrades ([MassivelyOP 2019][mop19]).
- **Main gameplay thread is expensive (documented, client-side 2013 quote):** "We are
  multi-threaded, but the primary gameplay thread is very expensive" ([AnandTech forum
  quote][at]).

**Takeaways:** even an engine built for this tops out around 1,000–2,000 per zone and
relies on (a) client authority for expensive checks, (b) aggressive per-client relevance
(you see ~200 of 2,000), (c) eliminating "check everyone in range" patterns. (a) is not
open to us: unmodified Minecraft clients are not authoritative. (b) and (c) are.

## Unreal Engine / Fortnite

Fortnite Battle Royale: **100 players and about 50,000 replicated actors** per server
([Epic: Replication Graph][rg]).

### Replication Graph (UE4/5, used by Fortnite)
- Default UE replication asks every actor, for every connection, every frame "should I
  send?". Epic says this "performs poorly" and bottlenecks server CPU at scale ([rg]).
- The graph replaces it with **persistent nodes** that keep precomputed actor lists
  across frames and **share them between connections**: a spatial grid puts each actor
  into the cells it can be seen/heard from; a client's list is read from its camera's
  cell. Per-client work becomes "fetch a list", not "evaluate every actor" ([rg]).
- **Dormancy:** static actors (Epic's example: a tree) send nothing until changed; dormant
  dynamic actors outside relevancy can be destroyed on the client after a TTL
  ([GridSpatialization2D API][grid]).

### Iris (UE5's newer replication system)
- **Dirty tracking (push model):** game code marks changed state; only dirty state is
  quantised and sent, instead of polling every object ([Iris intro][iris]).
- **Shared quantised state:** a full quantised copy of replicated state is kept so work is
  **shared across connections**; replication data is separated from game-thread data so
  more can run **in parallel** ([iris]).
- **Prioritisation with accumulation:** each object has a priority; below 1.0 it is skipped
  this frame, and **priority accumulates every tick until sent**, so distant objects are
  delayed, never starved. Default sphere prioritiser: full priority within an inner
  radius, falling with squared distance to 0.2 at the outer radius, 0.1 beyond
  ([Iris prioritization][prio]).
- **Filtering:** per-owner, per-connection, group and custom filters decide what a
  connection may receive at all ([Iris filtering][filt]).

## What Minecraft/Folia already does

- Spatial interest: Moonrise's `NearbyPlayers` chunk grid feeds the entity tracker
  (`ChunkMap.newTrackerTick`), comparable to the Replication Graph's grid.
- Per-type tracking range (our runs: players 128 blocks, animals/monsters 96) and fixed
  per-type update intervals (players every 2 ticks, items every 20; `EntityType`).
- Relative-move packets are already small deltas; bundles exist since 1.19.4.

What it does **not** do: the tracker runs on the region's owner thread; each packet is
encoded separately for every connection that receives it; update rate does not fall
with distance; there is no per-connection bandwidth budget or priority.

## Proposals for this project (ranked)

| # | Idea (source) | Tier | What it attacks |
|---|---|---|---|
| 1 | **Encode once, send many** (Iris shared state): serialise each entity update once, write the same bytes to every tracking connection | 0: no visible change | per-connection encoding cost, ~250 recipients per update in a dense city |
| 2 | **Tracker off the owner thread** (Iris: replication data separated from the game thread): compute visibility and build packets on helper threads from a per-tick snapshot | 0 | entity-tracker CPU on the one region thread |
| 3 | **Distance-tiered update rate** (Iris sphere prioritiser): e.g. every 2 ticks within 32 blocks, 4 within 64, 8 beyond; vanilla clients already interpolate entity movement | 1 | packet count and bandwidth (~5 Gbit/s estimate at 5,000) |
| 4 | **Per-connection budget with priority accumulation** (Iris): when a connection's per-tick budget is spent, defer lower-priority updates; deferred priority grows until sent | 1 | bandwidth spikes; graceful degradation instead of lag |
| 4b | **Coalesce superseded updates** (Source/CS2 snapshot model): an entity update still waiting in a connection's queue is replaced by the newer one (send only the latest position/metadata), not queued behind it; relative moves are re-based on the last *sent* position | 1 | bandwidth and queueing delay under load; pairs with #4 |
| 5 | **Interaction-only checks** (PlanetSide 2 NPC fix): replace "check every entity in range" loops with event-driven checks where vanilla semantics allow | 0–2, per case | per-tick scans in crowds |

1 and 2 change nothing players see, so they are the first CPU-track candidates; they also
fit the hybrid design in TICK_ARCHITECTURE.md (owner thread commits, helpers compute).
3 and 4 are Tier 1 and must be reported alongside vanilla-equivalent results. Client-side
authority (PlanetSide 2) and client prediction (Fortnite) are not available with
unmodified clients.

Next: profile the crowd baseline (per-phase timers + network bytes per tick) to size the
tracker and encoding cost before choosing between 1 and 2.

[fl]: https://en.wikipedia.org/wiki/ForgeLight
[s1]: https://steamcommunity.com/app/218230/discussions/0/1698294337777105091/
[psu]: https://www.planetside-universe.com/showthread.php?t=38520
[mop23]: https://massivelyop.com/2023/03/19/planetside-2-is-testing-out-server-improvements-faction-specific-abilities-and-gameplay-tweaks-on-pts/
[pts]: https://www.planetside2.com/patch-notes/pts-update-jan-31-23
[mop19]: https://massivelyop.com/2019/05/22/planetside-2-focuses-on-optimization-and-celebrates-planetside-1s-16th-birthday/
[at]: https://forums.anandtech.com/threads/eg-amd-cpus-performance-get-massive-boost-as-devs-optimize-next-gen-game-engines.2334933/post-35342140
[rg]: https://dev.epicgames.com/documentation/en-us/unreal-engine/replication-graph-in-unreal-engine
[grid]: https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/ReplicationGraph/UReplicationGraphNode_GridSpatia-
[iris]: https://dev.epicgames.com/documentation/en-us/unreal-engine/introduction-to-iris-in-unreal-engine
[prio]: https://dev.epicgames.com/documentation/en-us/unreal-engine/iris-prioritization-in-unreal-engine
[filt]: https://dev.epicgames.com/documentation/en-us/unreal-engine/iris-filtering-in-unreal-engine
