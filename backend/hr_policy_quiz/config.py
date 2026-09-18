import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} environment variable is required (set it in .env)")
    return value


class Settings:
    # Reuses the same MongoDB host as the rest of the platform, just a
    # separate logical database (see db.py) so collections never collide.
    MONGO_URI: str = _require("MONGO_CONNECTION_STRING")
    DB_NAME: str = _require("HR_QUIZ_DB_NAME")

    JWT_SECRET: str = _require("HR_QUIZ_JWT_SECRET")
    JWT_ALGORITHM: str = _require("HR_QUIZ_JWT_ALGORITHM")
    HR_TOKEN_EXPIRE_MINUTES: int = int(_require("HR_QUIZ_HR_TOKEN_EXPIRE_MINUTES"))
    CANDIDATE_TOKEN_EXPIRE_MINUTES: int = int(_require("HR_QUIZ_CANDIDATE_TOKEN_EXPIRE_MINUTES"))

    # Optional by design: blank just disables question-generation from new
    # uploads (see rag.py) - everything else keeps working without it.
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    QUIZ_QUESTION_COUNT: int = int(_require("HR_QUIZ_QUESTION_COUNT"))
    SECONDS_PER_QUESTION: int = int(_require("HR_QUIZ_SECONDS_PER_QUESTION"))


settings = Settings()
