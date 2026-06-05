# Spec: `retrieve()`

**File:** `retriever.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user's natural language query, find the most relevant chunks from the vector store using semantic similarity search. Return them ranked by relevance so that `generate_response()` can use them as context.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's natural language question |
| `n_results` | `int` | Maximum number of chunks to return (default: `N_RESULTS` from `config.py`) |

**Output:** `list[dict]`

Each dict in the returned list must contain exactly these keys:

| Key | Type | Description |
|-----|------|-------------|
| `"text"` | `str` | The chunk text |
| `"game"` | `str` | The game name this chunk came from |
| `"distance"` | `float` | Cosine distance score — lower means more similar to the query |

Results should be ordered from most to least relevant (lowest to highest distance). Returns an empty list `[]` if the collection contains no documents.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Query approach

*Describe how you will use `_collection.query()` to find relevant chunks. What arguments will you pass, and why?*

```
Call:
    results = _collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

Arguments and why:
  - query_texts=[query]
      A list (not a bare string) because query() is batch-capable. I pass a
      one-element list since retrieve() handles a single user question.
      Chroma embeds this text with the same model used at ingestion
      (all-MiniLM-L6-v2) so the query and the stored chunks live in the same
      vector space and can be compared.
  - n_results=n_results
      How many chunks to return, defaulting to N_RESULTS (3) from config.
      Kept as a parameter so callers can override it.
  - include=["documents", "metadatas", "distances"]
      The three fields I need to build the return dicts: the chunk text,
      the {"game": ...} metadata, and the cosine distance for ranking and
      threshold filtering. I deliberately omit "embeddings" — the raw
      vectors are large and unused, so fetching them would just waste memory.

I do NOT pass a "where" metadata filter: I want semantic search across all
games, not a pre-filter to one game. Game separation happens naturally
because each chunk carries its own "game" metadata.
```

---

### Return structure

*Sketch out what one item in your return list looks like as a concrete example. Where does each field come from in the query results?*

```
retrieve() returns a list[dict]. One item (the top result for the live test
query "What happens if you roll a 7 in Catan?") looks like:

    {
        "text": "x, that hex produces no resources that turn, regardless "
                "of the number rolled.\n\nROLLING A 7 ...",
        "game": "Catan",
        "distance": 0.47,
    }

Where each field comes from (after indexing [0] to drop the per-query outer
layer -- see "Handling the nested result structure" above):

    "text"     <- res["documents"][0][i]        the chunk text itself
    "game"     <- res["metadatas"][0][i]["game"] the metadata dict stored at
                                                 ingestion; pull the "game" key
    "distance" <- res["distances"][0][i]         cosine distance, lower = closer

i is the position in the result list. Because documents/metadatas/distances
are parallel lists, the same i indexes the matching field across all three,
so I build one dict per i (via zip or an index loop).

Ordering: query() already returns results sorted by ascending distance (most
to least similar), so iterating in order satisfies the spec's "most to least
relevant" requirement -- no extra sort needed.
```

---

### Handling the nested result structure

*`_collection.query()` returns nested lists. Describe what index you need to access to get the actual list of results for a single query, and why the nesting exists.*

```
Index needed: [0].

What query() returns: a dict (not a list), with keys including "ids",
"documents", "metadatas", and "distances". Each of those values is a
LIST OF LISTS shaped [num_queries][n_results]:

    res["distances"] == [[0.47, 0.54, 0.62]]
                         ^                  ^
                         outer = one entry per query submitted
                                            inner = the n_results for that query

Why the nesting exists: query_texts is a list, so query() is batch-capable
-- you can pass many questions at once and it returns one result-set per
question. The outer dimension is "which query." I only ever pass a single
query, so the outer length is always 1, and I take [0] to drop that layer
and get the actual results:

    docs      = res["documents"][0]
    metas     = res["metadatas"][0]
    distances = res["distances"][0]

Key follow-on: after indexing [0], these three lists are parallel /
position-aligned -- docs[i], metas[i], distances[i] all describe the SAME
chunk. So I build my return list by zipping them together, one dict per
position:
    {"text": docs[i], "game": metas[i]["game"], "distance": distances[i]}

(Verified live against the 149-chunk store: query "What happens if you roll
a 7 in Catan?" returned outer len 1, inner len 3, distances [0.47, 0.54,
0.62], top metadata {'game': 'Catan'}.)
```

---

### Relevance threshold

*Will you filter out results above a certain distance score, or return all `n_results` regardless of how relevant they are? What are the tradeoffs of each approach?*

```
Decision: filter by a distance threshold, but defer the exact cutoff value
until implementation (tune it against real measured distances).

Why filter at all:
query() always returns the top n_results ranked by distance — even for an
off-topic question. "Closest" is not the same as "relevant." If I never
filter, retrieve() can never return [], which makes generate_response()'s
"I couldn't find anything in the loaded rules" branch dead code. RulesBot
would then ALWAYS try to answer, producing confident hallucinations on
out-of-scope questions. Filtering is what makes the honest "not in the
rules" behavior possible — and grounding is the whole point of this app.

Approach: keep chunks whose distance <= THRESHOLD; if none qualify, return [].

Tradeoffs:
  - Filter (chosen):
      + enables the honest "I don't know" response
      + gives the generator cleaner, on-topic context
      - introduces a magic number to tune
      - too strict -> rejects valid questions (says "no info" when info exists)
      - too loose  -> lets junk through (no better than not filtering)
  - No filter:
      + simpler, never accidentally hides a good chunk
      - can never say "I don't know" -> hallucinates on off-topic queries

Why defer the number (not pick it from theory):
the right cutoff depends on the actual distance distribution of this model
(all-MiniLM-L6-v2) over these 149 chunks — it can't be derived in the
abstract. Plan: measure during implementation by running an in-scope query
("What happens if you roll a 7 in Catan?") and an out-of-scope query
("What's the weather today?"), record each top distance, and set the
threshold in the gap between them. Cosine distance runs 0 (identical) ->
~1 (unrelated), so my starting hypothesis is a lenient cutoff around ~1.0
(reject only clearly-bad matches), then tighten based on measured numbers.
Final tuned value recorded in Implementation Notes below.
```

---

### Edge cases

*How does your implementation behave when: (a) the collection is empty, (b) the query matches no chunks well, (c) the query matches chunks from multiple games?*

```
(a) Empty collection:
    A guard at the top — `if _collection.count() == 0: return []` — short-
    circuits before querying. This avoids querying an empty store and gives
    generate_response() its empty-list signal, so the bot says it has no
    loaded rules rather than erroring.

(b) Query matches no chunks well (off-topic question):
    query() still returns its top n_results (it always does), but every
    distance is above MAX_DISTANCE (0.75), so the threshold filter drops them
    all and retrieve() returns []. Verified: "What's the weather today?" ->
    [] (top distances ~0.86). The empty list flows to generate_response(),
    which answers "not in the loaded rules" instead of hallucinating.

(c) Query matches multiple games:
    No special handling needed — and that's intentional. Results are ranked
    purely by distance across all games, and each returned dict carries its
    own "game" field. So a generic question naturally returns a mix.
    Verified: "How do you win?" -> Monopoly (0.507), Risk (0.509), Ticket to
    Ride (0.522). generate_response() can then label which game each part of
    the answer comes from, instead of silently blending rules from different
    games.
```

---

## Implementation Notes

*Fill this in after implementing, before moving to Milestone 3.*

**Test query and top result returned:**

```
Query: "What happens when you roll a 7?"
Top result game: Catan
Distance score: 0.466
Does it make sense? Yes — the top hit is the Catan chunk about rolling a 7
(no resource production / robber). It is clearly ahead of the next results
(Risk dice chunks at 0.597, 0.610), so the ranking points at the right game.

Also tested:
- "How do you win?" (multi-game): returned Monopoly (0.507), Risk (0.509),
  Ticket to Ride (0.522) — three different games, all about winning, with
  tightly clustered distances. Correct behavior: no single game "owns" a
  generic question, and the close scores reflect that.
- "What's the weather today?" (out-of-scope): returned [] — every candidate
  was past MAX_DISTANCE (0.75), so the bot can honestly say "not in the rules."

Tuned threshold: MAX_DISTANCE = 0.75. Measured gap — in-scope queries top out
~0.63, off-topic queries start ~0.85; 0.75 sits cleanly in between.
```

**One thing about the query results that surprised you:**

```
I expected that when a query returned chunks from the WRONG game, the culprit
would be chunks that are too small to carry semantic signal. So I printed the
stored chunks to check — and the assumption was wrong. The chunks are full
size (149 chunks, median length 300 chars, min 62). The real artifact is that
119 of 149 chunks START MID-WORD/MID-SENTENCE (their first character is
lowercase) — e.g. the top Catan hit begins "x, that hex produces..." where
"x," is the chopped tail of a word.

So the issue is not chunk SIZE but chunk BOUNDARIES: character-based splitting
(chunk_document) cuts at character 300 regardless of word/sentence boundaries,
which blurs the semantic signal. This is exactly the "Known limitations" note
in the chunk-document spec, now confirmed with real data.

Second smaller surprise: "roll a 7" pulls in Risk dice-combat chunks. That is
NOT a bug — "rolling dice" is genuinely semantically similar across games. The
distance ordering still correctly puts Catan first; the game label on each
chunk is what lets generate_response() keep the answer grounded in the right
game.
```
