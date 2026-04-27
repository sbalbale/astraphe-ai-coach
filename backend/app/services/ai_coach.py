import google.generativeai as genai
from app.config import settings

# Configure Gemini using centralized settings
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel(settings.GEMINI_MODEL)

def load_coach_instructions() -> str:
    """
    Reads the AI's persona and rules from the markdown file.
    Uses the directory defined in config.py.
    """
    prompt_file = settings.PROMPTS_DIR / settings.COACH_PROMPT_FILE
    
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback to a basic instruction if the .md file is missing
        return "You are ASTRAPE, an elite, data-driven performance coach."

def get_coach_response(athlete_id: str, message: str, current_tss: float = 0.0) -> str:
    """
    Sends the athlete's message to Gemini, augmented with physiological data
    and dynamically loaded instructions.
    """
    # 1. Load the "Brain" of the coach
    system_instruction = load_coach_instructions()
    
    # 2. Assemble the dynamic context block
    context_block = f"""
    [SYSTEM CONTEXT - DO NOT SHOW TO USER]
    Athlete ID: {athlete_id}
    Most recent workout TSS: {current_tss}
    [END CONTEXT]
    """
    
    # 3. Combine rules, data, and the athlete's message
    final_prompt = f"{system_instruction}\n\n{context_block}\n\nAthlete Message: {message}"
    
    # 4. Generate the response
    response = model.generate_content(final_prompt)
    
    return response.text