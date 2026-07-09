// Placeholder data used across Results and Debate pages until AI integration is added.

// The 4 models that actually participate in the comparison flow.
export const MODELS = [
  {
    id: "model-a",
    label: "ChatGPT",
    codename: "GPT-5.4",
    provider: "OpenAI",
    accent: "#10A37F",
    accentClass: "model-bar-a",
    latencyMs: 812,
    tokens: 428,
    initials: "GT",
  },
  {
    id: "model-b",
    label: "Claude",
    codename: "Sonnet 4.6",
    provider: "Anthropic",
    accent: "#D97757",
    accentClass: "model-bar-b",
    latencyMs: 1120,
    tokens: 512,
    initials: "CL",
  },
  {
    id: "model-c",
    label: "Gemini",
    codename: "3.1 Pro",
    provider: "Google DeepMind",
    accent: "#4285F4",
    accentClass: "model-bar-c",
    latencyMs: 940,
    tokens: 389,
    initials: "GE",
  },
  {
    id: "model-d",
    label: "Grok",
    codename: "3.0",
    provider: "xAI",
    accent: "#F43F5E",
    accentClass: "model-bar-d",
    latencyMs: 1305,
    tokens: 471,
    initials: "GR",
  },
];

// All models advertised on the marketing "Supported Models" section.
export const SUPPORTED_MODELS = [
  { id: "chatgpt", name: "ChatGPT",  provider: "OpenAI",         accent: "#10A37F", initials: "GT" },
  { id: "gemini",  name: "Gemini",   provider: "Google DeepMind", accent: "#4285F4", initials: "GE" },
  { id: "claude",  name: "Claude",   provider: "Anthropic",       accent: "#D97757", initials: "CL" },
  { id: "grok",    name: "Grok",     provider: "xAI",             accent: "#F43F5E", initials: "GR" },
  { id: "mistral", name: "Mistral",  provider: "Mistral AI",      accent: "#FF7A00", initials: "MI" },
  { id: "deepseek",name: "DeepSeek", provider: "DeepSeek",        accent: "#7C3AED", initials: "DS" },
];

// Conclusion strategy presets (used before submit).
export const STRATEGIES = [
  { id: "max_accuracy",   label: "Maximum Accuracy",   hint: "Prioritise verified facts and cite consensus above novelty." },
  { id: "balanced",       label: "Balanced",           hint: "Even weight on accuracy, nuance and clarity." },
  { id: "creative",       label: "Creative Thinking",  hint: "Reward unexpected framings and lateral connections." },
  { id: "critical",       label: "Critical Analysis",  hint: "Actively surface counter-arguments and edge cases." },
  { id: "fast",           label: "Fast Response",      hint: "Shortest defensible answer with the top argument." },
];

// The 7-step workflow visualisation.
export const WORKFLOW_STEPS = [
  { id: "question",   title: "Question",              body: "You ask anything." },
  { id: "models",     title: "Multiple AI Models",    body: "Four leading models answer independently." },
  { id: "consensus",  title: "Consensus Analysis",    body: "We compare their reasoning side-by-side." },
  { id: "evidence",   title: "Evidence Review",       body: "Claims are checked for logical consistency." },
  { id: "conclusion", title: "Trusted Conclusion",    body: "One transparent, explainable answer." },
  { id: "challenge",  title: "Challenge Conclusion",  body: "Optionally stress-test it against every model." },
  { id: "updated",    title: "Updated Conclusion",    body: "The conclusion evolves as evidence changes." },
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
  confidence: 82,
  agreementPoints: [
    "Data is partitioned (sharded) across multiple nodes for horizontal scale.",
    "Replication provides fault tolerance and higher availability.",
    "The CAP theorem forces a tradeoff between consistency and availability under partition.",
    "Consensus protocols (Raft, Paxos) are used to keep replicas coordinated.",
  ],
  disagreementPoints: [
    "Claude emphasises leaderless replication as the default; Gemini treats single-leader as the more common baseline.",
    "Grok lists sharding, replication and consensus as the primary axes; Gemini uses partitioning, replication and conflict resolution instead.",
  ],
  uncertaintyPoints: [
    "Real-world CAP tradeoffs are workload-dependent — the answer changes for OLTP vs analytics.",
    "New protocols (e.g. Aurora Limitless, TigerBeetle) blur the classic single-vs-multi-leader distinction.",
  ],
};

// Why this conclusion — the transparency block on the Trusted Conclusion card.
export const MOCK_WHY = [
  "All four models converged on the three-axis design frame (partitioning, replication, consensus).",
  "The CAP theorem appears in every response and is treated as the forcing function — high signal.",
  "Disagreements were about defaults, not fundamentals — safely resolvable by naming both sides.",
  "The Critical Analysis strategy surfaced modern softeners (tunable consistency, HLCs) as a caveat.",
];

export const MOCK_SUPER_ANSWER = `A distributed database is a database whose data and workload live across many cooperating nodes, presented to clients as a single system. This architecture buys you three things: horizontal scale, fault tolerance through replication, and lower latency via geo-locality.

Every distributed database is defined by three decisions:

1. **Partitioning** — how data is split across nodes (hash vs. range sharding).
2. **Replication** — how many copies exist and how they stay in sync (synchronous vs. asynchronous, single-leader vs. multi-leader vs. leaderless).
3. **Consensus** — how the cluster agrees on the truth when nodes disagree (Raft, Paxos, or leaderless quorum protocols).

Because network partitions are inevitable at scale, the CAP theorem forces a deliberate choice: strict consistency (CockroachDB, Spanner) or full availability with eventual consistency (Cassandra, Dynamo). Modern systems soften the tradeoff with tunable consistency and hybrid logical clocks, but the fundamental choice remains.

In short: distributed databases trade the simplicity of one machine for the scale and resilience of many — and the entire design space is about managing that tradeoff.`;

// How much each model contributed to the final Trusted Conclusion.
export const MOCK_CONTRIBUTIONS = [
  { modelId: "model-a", pct: 34 },
  { modelId: "model-b", pct: 28 },
  { modelId: "model-c", pct: 23 },
  { modelId: "model-d", pct: 15 },
];

// Consensus-analysis animated messages shown between model completion and reveal.
export const ANALYSIS_STEPS = [
  "Comparing answers...",
  "Finding agreements...",
  "Finding disagreements...",
  "Checking logical consistency...",
  "Highlighting uncertainty...",
  "Ranking strongest arguments...",
  "Preparing final conclusion...",
];

// Challenge phase — what each model attacks the current conclusion for.
export const CHALLENGE_STEPS = [
  "Scanning for missing evidence...",
  "Probing for logical flaws...",
  "Considering alternative interpretations...",
  "Checking for contradictions...",
  "Exploring exceptions and edge cases...",
  "Cross-referencing recent information...",
];

// Two possible outcomes of the Challenge — we pick one deterministically on first click.
export const CHALLENGE_OUTCOMES = {
  strengthened: {
    result: "strengthened",
    newConfidence: 94,
    headline: "Conclusion strengthened",
    body: "No stronger contradictory evidence was found. The three-axis frame held up under adversarial review, and the CAP-softener caveat was confirmed as accurate.",
    findings: [
      "All four models re-verified the CAP theorem framing under critical analysis.",
      "Alternative frames (e.g. reads-vs-writes-first) resolved back into the same three axes.",
      "No missing evidence surfaced from the last-24h information sweep.",
    ],
  },
  weakened: {
    result: "weakened",
    newConfidence: 68,
    headline: "New evidence identified",
    body: "The challenge surfaced a caveat that materially affects the conclusion for very-large-scale multi-region systems. The confidence has been reduced accordingly.",
    findings: [
      "Modern hybrid systems (e.g. Spanner TrueTime, Aurora Limitless) partially escape the classical CAP tradeoff.",
      "Grok highlighted an exception in globally-distributed OLAP workloads.",
      "Claude flagged that the answer is workload-dependent — not a single universal truth.",
    ],
  },
};

export const TRANSPARENCY_NOTE =
  "This conclusion is generated from the strongest consensus among multiple AI models based on the available information. It is designed to support decision-making, not replace human judgment.";

export const MOCK_DEBATE = [
  { model: "model-a", text: "Let me start with the textbook framing: a distributed database is a database whose state lives on multiple nodes that cooperate over a network." },
  { model: "model-b", text: "That's technically correct but a little dry. Users care *why* they'd want one. I'd lead with the benefits: fault tolerance, elastic scale, and geo-locality." },
  { model: "model-c", text: "Fair point. But we shouldn't skip the design tradeoffs. The interesting question is how data is partitioned, replicated, and how conflicts are resolved." },
  { model: "model-d", text: "I'd compress that to three axes: sharding, replication, consensus. Everything else falls out of those decisions." },
  { model: "model-a", text: "Agreed on the three axes. But we also need to name the CAP theorem — it's the reason every distributed database has a personality." },
  { model: "model-b", text: "Good call. CAP is the honest tradeoff. Spanner and CockroachDB pick consistency; Cassandra picks availability. Users need to know what their database chose for them." },
  { model: "model-c", text: "One more nuance: modern systems soften CAP with tunable consistency and hybrid logical clocks. It's not always a binary choice anymore." },
  { model: "model-d", text: "Then let's synthesize: definition, three design axes, CAP as the forcing function, modern softeners. Anything else is over-explaining." },
  { model: "model-a", text: "Consensus reached. That structure covers 90% of what a curious developer needs to know without drowning in academic detail." },
];
