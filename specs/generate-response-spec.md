# Spec: `generate_response()`

**File:** `generator.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user query and a list of retrieved rule chunks, generate a response that directly answers the question using only the retrieved text as context. The response must be grounded — it should not draw on the model's general knowledge of board games, only on what was retrieved.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's original question |
| `retrieved_chunks` | `list[dict]` | Ranked list of chunks from `retrieve()`, each with `"text"`, `"game"`, and `"distance"` |

**Output:** `str`

A plain string containing the response to show the user. The response should:
- Answer the question using only the retrieved rule text
- Identify which game the answer comes from
- Acknowledge clearly when the answer is not found in the loaded rules

Returns a fallback string (not an error) when `retrieved_chunks` is empty.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Context formatting

*How will you format the retrieved chunks before passing them to the LLM? Describe the structure — not the code. Consider: will you label chunks by game? Include distance scores? Separate chunks with delimiters?*

```
Each chunk is rendered as its own labeled block, separated by a clear
delimiter so the model can tell where one chunk ends and the next begins:

    [Game: Catan]
    <chunk text>

    ---

    [Game: Risk]
    <chunk text>

Decisions:
  - Label by game: YES. The game name is prepended to every chunk so the
    model can cite the correct game and so it doesn't blend rules from two
    different games into one answer (important for "How do you win?"-type
    queries that legitimately return multiple games).
  - Include distance scores: NO. Distance is a retrieval-internal signal
    (used by retrieve()'s threshold), not something the model should reason
    about or leak into its answer. Showing it would just add noise.
  - Delimiter between chunks: YES ("---" on its own line). Clear boundaries
    stop the model from running two unrelated chunks together as if they were
    one continuous rule.
```

---

### System prompt — grounding instruction

*Write the exact system prompt instruction you will use to prevent the model from answering beyond the retrieved text. This is the most important design decision in this function.*

```
"Answer the question using ONLY the rule text provided in the context below.
Do not use any outside knowledge about board games, even if you are confident
you know the answer. If the provided context does not contain the answer, do
not guess — say that the loaded rules don't cover it. A correct 'I don't know'
is better than a confident wrong answer."

Reasoning: this is the core of grounding. The two failure modes I'm guarding
against are (1) the model answering from its own training knowledge of, say,
Monopoly instead of the retrieved text, and (2) the model confabulating when
the context is thin. The instruction explicitly forbids outside knowledge AND
gives an escape hatch (admit ignorance) so the model isn't pressured to invent
an answer.
```

---

### System prompt — citation instruction

*Write the exact instruction you will use to tell the model to identify which game its answer comes from.*

```
"Always state which game your answer is about. Each context block is labeled
with its game as [Game: <name>] — use that label. Begin your answer by naming
the game, e.g. 'In Catan, ...'. If the answer draws on more than one game,
make clear which rule belongs to which game."

Reasoning: the user may ask a question that pulls chunks from several games
(verified: "How do you win?" returned Monopoly, Risk, and Ticket to Ride).
Naming the game prevents the answer from silently mixing rules, and it tells
the user where the information came from so they can trust it.
```

---

### Fallback behavior

*What should the response say when the answer isn't found in the loaded rule books? Write the exact fallback message.*

```
There are two distinct "not found" situations:

1. retrieve() returned NO chunks at all (off-topic question, everything past
   the distance threshold). generate_response() short-circuits before calling
   the LLM and returns this exact string (no API call needed):

   "I couldn't find anything about that in the loaded rule books. I can only
   answer questions about these games: Catan, Clue, Codenames, Monopoly,
   Pandemic, Risk, Ticket to Ride, and Uno."

2. Chunks were retrieved but they don't actually contain the answer. This is
   handled by the LLM via the grounding instruction (it is told to say the
   loaded rules don't cover it rather than guess), not by a hardcoded string.

Why list the supported games in the fallback: it turns a dead end into useful
guidance — the user learns what RulesBot CAN answer instead of just being told
"no."
```

---

### Handling low-relevance chunks

*`retrieved_chunks` may include chunks with high distance scores (weak relevance). Will you filter these out before building context, pass them all in, or handle them another way? What are the tradeoffs?*

```
Decision: do NOT filter again here. retrieve() already applies the distance
threshold (MAX_DISTANCE = 0.75), so every chunk that reaches
generate_response() has already cleared the relevance bar. Re-filtering here
would duplicate that logic in two places and risk the two thresholds drifting
out of sync.

generate_response() trusts retrieve() as the single source of truth for "is
this relevant enough," and trusts the grounding system prompt as the second
line of defense: even if a borderline chunk slips through, the model is
instructed to answer only from context and to admit when the rules don't
cover the question.

Tradeoffs:
  - Single threshold (chosen): one place to tune relevance; clean separation
    of concerns (retrieve = relevance, generate = phrasing). Risk: if the
    retrieve threshold is too loose, weak chunks reach the LLM.
  - Second filter here: could be stricter for generation than for retrieval,
    but adds a second magic number and splits relevance logic across two
    functions. Not worth it for this app.
```

---

### Message structure

*Describe how you will structure the messages list for the API call — what goes in the system message vs. the user message?*

```
Two messages:

  system: the fixed instructions — role ("you are RulesBot, a board game rules
          assistant"), the grounding instruction, the citation instruction.
          These never change between requests, so they belong in the system
          message where they set the model's behavior for the whole turn.

  user:   the per-request content — the formatted context block (the labeled
          chunks) followed by the user's actual question. Putting the context
          in the user message keeps the system message stable and clearly
          separates "here is the data for THIS question" from "here is how you
          should always behave."

Shape:
  [
    {"role": "system", "content": <grounding + citation instructions>},
    {"role": "user",   "content": "Context from the rule books:\n\n"
                                  "<formatted chunks>\n\n"
                                  "Question: <query>"},
  ]

Generation setting: temperature is kept low (~0.2) because this is a factual
grounding task — I want consistent, faithful answers, not creative variation.
```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Test query and response:**

```
Query: "What happens when you roll a 7 in Catan?"
Response (abbrev): "In Catan, when a 7 is rolled... no resources are produced,
  and every player with more than 7 resource cards must discard half. The
  player who rolled moves the robber and steals one resource."
Correctly grounded? Yes — matches the retrieved Catan chunks (no production,
  robber move + steal); no outside facts invented.
Cited the right game? Yes — opens with "In Catan, ...".

Other tests (direct pipeline):
- "What's the weather today?" -> 0 chunks -> fallback string returned with NO
  API call. Lists the 8 supported games.
- Grounding stress test: "What is the airspeed velocity of an unladen swallow
  in Monopoly?" -> 1 chunk retrieved, but the model correctly answered "the
  loaded rules don't cover [it]" and named Monopoly instead of inventing an
  answer. Confirms the grounding instruction works even when a (weak) chunk
  is present.

Verified end-to-end through the LIVE Gradio UI (not just direct calls):
- "What happens when you roll a 7 in Catan?" -> grounded Catan answer
- "How does the Spymaster give clues in Codenames?" -> grounded Codenames
  answer (word + number clue), correctly cited
- "What's the capital of France?" -> fallback message, no hallucination
```

**One thing you changed from your original spec after seeing the actual output:**

```
Originally I planned a single generic fallback for "not found." After testing,
I realized there are TWO distinct cases that need DIFFERENT handling, and split
them: (1) zero chunks retrieved -> a hardcoded fallback returned WITHOUT an API
call (no point paying for a call with no context), and (2) chunks retrieved but
they don't answer -> handled by the LLM via the grounding instruction. The
stress-test query proved case (2) is real and that the system prompt, not a
hardcoded string, is what catches it.

Also noted: the groq SDK (0.15.0) emitted a Pydantic-v1/Python-3.14
compatibility UserWarning. Non-fatal (calls succeeded), but same class of
issue as the gradio 5.20->5.50 fix, so I bumped groq 0.15.0 -> 1.4.0. The
chat.completions.create() API is unchanged across that bump, and the warning
is now gone.
```
