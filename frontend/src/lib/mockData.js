// Placeholder data used across Results and Debate pages until AI integration is added.

export const MODELS = [
  {
    id: "model-a",
    label: "Model A",
    codename: "Nova-1",
    provider: "Nova Systems",
    accent: "#00E5FF",
    accentClass: "model-bar-a",
    latencyMs: 812,
    tokens: 428,
  },
  {
    id: "model-b",
    label: "Model B",
    codename: "Ember-3",
    provider: "Ember Labs",
    accent: "#10B981",
    accentClass: "model-bar-b",
    latencyMs: 1120,
    tokens: 512,
  },
  {
    id: "model-c",
    label: "Model C",
    codename: "Prism-2",
    provider: "Prism AI",
    accent: "#F59E0B",
    accentClass: "model-bar-c",
    latencyMs: 940,
    tokens: 389,
  },
  {
    id: "model-d",
    label: "Model D",
    codename: "Kairo-X",
    provider: "Kairo Research",
    accent: "#F43F5E",
    accentClass: "model-bar-d",
    latencyMs: 1305,
    tokens: 471,
  },
];

export const MOCK_RESPONSES = {
  "model-a": `A distributed database splits data across many machines so no single server holds all of it. This gives you horizontal scale — more machines mean more capacity — and higher availability, because losing one node does not mean losing the whole system.

The tradeoff is the CAP theorem: under a network partition you must choose between strict consistency and full availability. Modern systems like CockroachDB or Spanner pick consistency; others like Cassandra pick availability and offer eventual consistency.`,
  "model-b": `Think of a distributed database as a coordinated team of servers rather than a single warehouse. Each node holds a slice of your data (a shard) and often a replica of another node's slice.

Key benefits:
• Fault tolerance — replicas keep serving reads if a node fails.
• Elastic scale — add nodes to grow throughput linearly.
• Geo-locality — data can live near the users who query it.

Common patterns include leaderless replication (Dynamo-style), Raft/Paxos consensus, and hybrid logical clocks for ordering.`,
  "model-c": `Distributed databases spread data across multiple physical or virtual nodes to improve scale, resilience, and locality. They differ from replicated single-node databases in that both reads and writes can be served from any participating node.

The design space is defined by three axes: how data is partitioned (hash vs. range), how updates are replicated (synchronous vs. asynchronous), and how conflicts are resolved (single-leader, multi-leader, or leaderless).

Because network partitions are unavoidable at scale, every distributed database makes a deliberate choice on the CAP spectrum.`,
  "model-d": `Short version: a distributed database is a database that lives on more than one machine and cooperates so that clients see it as one system.

The interesting part is *how* it cooperates. You get three big design decisions:
1. Sharding — how data is split.
2. Replication — how many copies exist and how they stay in sync.
3. Consensus — how the cluster agrees on the truth when nodes disagree.

Get these right and you gain scale, durability, and low latency. Get them wrong and you get split brain, phantom writes, or lost data.`,
};

export const MOCK_SCORES = {
  consensus: 87,
  trust: 92,
  agreementPoints: [
    "Data is partitioned (sharded) across multiple nodes for horizontal scale.",
    "Replication provides fault tolerance and higher availability.",
    "The CAP theorem forces a tradeoff between consistency and availability under partition.",
    "Consensus protocols (Raft, Paxos) are used to keep replicas coordinated.",
  ],
  disagreementPoints: [
    "Model B emphasizes leaderless replication as the default; Model C treats single-leader as the more common baseline.",
    "Model D lists sharding, replication and consensus as the primary axes; Model C uses partitioning, replication and conflict resolution instead.",
  ],
};

export const MOCK_SUPER_ANSWER = `A distributed database is a database whose data and workload live across many cooperating nodes, presented to clients as a single system. This architecture buys you three things: horizontal scale, fault tolerance through replication, and lower latency via geo-locality.

Every distributed database is defined by three decisions:

1. **Partitioning** — how data is split across nodes (hash vs. range sharding).
2. **Replication** — how many copies exist and how they stay in sync (synchronous vs. asynchronous, single-leader vs. multi-leader vs. leaderless).
3. **Consensus** — how the cluster agrees on the truth when nodes disagree (Raft, Paxos, or leaderless quorum protocols).

Because network partitions are inevitable at scale, the CAP theorem forces a deliberate choice: strict consistency (CockroachDB, Spanner) or full availability with eventual consistency (Cassandra, Dynamo). Modern systems soften the tradeoff with tunable consistency and hybrid logical clocks, but the fundamental choice remains.

In short: distributed databases trade the simplicity of one machine for the scale and resilience of many — and the entire design space is about managing that tradeoff.`;

export const MOCK_DEBATE = [
  {
    model: "model-a",
    text: "Let me start with the textbook framing: a distributed database is a database whose state lives on multiple nodes that cooperate over a network.",
  },
  {
    model: "model-b",
    text: "That's technically correct but a little dry. Users care *why* they'd want one. I'd lead with the benefits: fault tolerance, elastic scale, and geo-locality.",
  },
  {
    model: "model-c",
    text: "Fair point. But we shouldn't skip the design tradeoffs. The interesting question is how data is partitioned, replicated, and how conflicts are resolved.",
  },
  {
    model: "model-d",
    text: "I'd compress that to three axes: sharding, replication, consensus. Everything else falls out of those decisions.",
  },
  {
    model: "model-a",
    text: "Agreed on the three axes. But we also need to name the CAP theorem — it's the reason every distributed database has a personality.",
  },
  {
    model: "model-b",
    text: "Good call. CAP is the honest tradeoff. Spanner and CockroachDB pick consistency; Cassandra picks availability. Users need to know what their database chose for them.",
  },
  {
    model: "model-c",
    text: "One more nuance: modern systems soften CAP with tunable consistency and hybrid logical clocks. It's not always a binary choice anymore.",
  },
  {
    model: "model-d",
    text: "Then let's synthesize: definition, three design axes, CAP as the forcing function, modern softeners. Anything else is over-explaining.",
  },
  {
    model: "model-a",
    text: "Consensus reached. That structure covers 90% of what a curious developer needs to know without drowning in academic detail.",
  },
];
