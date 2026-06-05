import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"

# --- Embeddings ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# --- Vector store ---
CHROMA_COLLECTION = "rulesbot"
CHROMA_PATH = "./chroma_db"

# --- Retrieval ---
N_RESULTS = 3
# Max cosine distance for a chunk to count as relevant. Chunks farther than
# this are dropped so off-topic questions return nothing (and the bot can say
# "not in the rules") rather than answering from weak matches. Tuned from
# measured distances: in-scope queries top out ~0.63, off-topic start ~0.85,
# so 0.75 sits in the gap. See specs/retrieve-spec.md.
MAX_DISTANCE = 0.75

# --- Documents ---
DOCS_PATH = "./docs"
