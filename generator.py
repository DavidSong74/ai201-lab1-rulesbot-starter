from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL

_client = Groq(api_key=GROQ_API_KEY)


def generate_response(query, retrieved_chunks):
    """
    Generate a grounded answer from retrieved rule chunks.

    TODO — Milestone 3:

    `retrieved_chunks` is the list returned by retrieve(). Each item is a dict:
      - "text"     : the chunk text
      - "game"     : the game name
      - "distance" : similarity score (you can use this to filter weak matches)

    Before writing code, talk through these with your group:
      - How will you format the chunks into a context block for the prompt?
      - What instructions will stop the model from answering beyond what the
        rules say? (Grounding is the whole point — a confident wrong answer
        is worse than an honest "I don't know.")
      - How will you surface which game each answer comes from?

    Your response should:
      1. Answer using only the retrieved context — not the model's general knowledge
      2. Make clear which game the answer comes from
      3. Say so clearly when the answer isn't in the loaded rules

    Return the response as a plain string.
    """
    # Case 1: retrieve() found nothing relevant (off-topic question). Answer
    # directly without an API call — there's nothing to ground an answer in.
    if not retrieved_chunks:
        return (
            "I couldn't find anything about that in the loaded rule books. "
            "I can only answer questions about these games: Catan, Clue, "
            "Codenames, Monopoly, Pandemic, Risk, Ticket to Ride, and Uno."
        )

    # Format each chunk as a game-labeled block, separated by a delimiter so
    # the model can tell chunks (and games) apart. Distance is intentionally
    # omitted — it's a retrieval-internal signal, not context for the model.
    context = "\n\n---\n\n".join(
        f"[Game: {chunk['game']}]\n{chunk['text']}" for chunk in retrieved_chunks
    )

    # System message: fixed behavior — grounding + citation. These never change
    # per request, so they belong here rather than in the user message.
    system_prompt = (
        "You are RulesBot, a board game rules assistant. Answer the question "
        "using ONLY the rule text provided in the context. Do not use any "
        "outside knowledge about board games, even if you are confident you "
        "know the answer. If the provided context does not contain the answer, "
        "do not guess — say that the loaded rules don't cover it. A correct "
        "'I don't know' is better than a confident wrong answer.\n\n"
        "Always state which game your answer is about. Each context block is "
        "labeled with its game as [Game: <name>] — use that label and begin "
        "your answer by naming the game, e.g. 'In Catan, ...'. If the answer "
        "draws on more than one game, make clear which rule belongs to which."
    )

    # User message: the per-request context block plus the actual question.
    user_message = (
        f"Context from the rule books:\n\n{context}\n\n"
        f"Question: {query}"
    )

    response = _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,  # low — this is a factual grounding task, not creative
    )

    return response.choices[0].message.content
