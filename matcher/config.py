import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _env_bool(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    career_ops_dir: str = os.environ.get("CAREER_OPS_DIR", "career-ops")
    nvidia_api_key: str = _env("NVIDIA_API_KEY")
    nvidia_model: str = os.environ.get(
        "NVIDIA_MODEL",
        "meta/llama-4-maverick-17b-128e-instruct",
    )
    nvidia_base_url: str = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    nvidia_nim_base_url: str = os.environ.get("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    nvidia_chat_completions_url: str = os.environ.get("NVIDIA_CHAT_COMPLETIONS_URL", "")
    nvidia_nim_chat_completions_url: str = os.environ.get("NVIDIA_NIM_CHAT_COMPLETIONS_URL", "")
    nvidia_ensemble_scorers: list[str] = field(
        default_factory=lambda: _env_csv(
            "NVIDIA_ENSEMBLE_SCORERS",
            "meta/llama-4-maverick-17b-128e-instruct,moonshotai/kimi-k2.6,nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
    )
    nvidia_ensemble_synthesizer: str = os.environ.get(
        "NVIDIA_ENSEMBLE_SYNTHESIZER",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    )
    use_jsonld_input: bool = _env_bool("USE_JSONLD_INPUT", "")
    matcher_port: int = int(os.environ.get("MATCHER_PORT", "8001"))
    state_dir: str = os.environ.get("STATE_DIR", "/app/state")
    ensemble_job_concurrency: int = int(os.environ.get("ENSEMBLE_JOB_CONCURRENCY", "1"))


settings = Settings()
