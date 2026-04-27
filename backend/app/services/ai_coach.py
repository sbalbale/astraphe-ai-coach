import google.generativeai as genai
from app.config import settings
import json
from datetime import date
from supabase import Client

genai.configure(api_key=settings.GEMINI_API_KEY)

def get_embedding_model_name() -> str:
    embedding_model = settings.GEMINI_EMBEDDING_MODEL
    return embedding_model if embedding_model.startswith("models/") else f"models/{embedding_model}"

def load_coach_instructions() -> str:
    prompt_file = settings.PROMPTS_DIR / settings.COACH_PROMPT_FILE
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are ASTRAPE, an elite, data-driven performance coach."

async def retrieve_relevant_memories(athlete_id: str, query: str, db: Client, top_k: int = 5) -> list[dict]:
    embedding_model = genai.embed_content(
        model=get_embedding_model_name(),
        content=query,
        task_type="retrieval_query",
    )
    query_embedding = embedding_model["embedding"]
    result = db.rpc("match_coach_memories", {
        "athlete_id": athlete_id, "query_embedding": query_embedding, "match_threshold": 0.75, "match_count": top_k
    }).execute()
    return result.data

def get_coach_response(athlete_id: str, message: str, current_tss: float = 0.0) -> str:
    system_instruction = load_coach_instructions()
    context_block = f"[SYSTEM CONTEXT - DO NOT SHOW TO USER]\nAthlete ID: {athlete_id}\nMost recent workout TSS: {current_tss}\n[END CONTEXT]"
    final_prompt = f"{system_instruction}\n\n{context_block}\n\nAthlete Message: {message}"
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    response = model.generate_content(final_prompt)
    return response.text