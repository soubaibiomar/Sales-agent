"""
Configuration settings for local AI model constraints and resource budgeting.
"""
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AIModelConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    # Inference execution mode
    inference_mode: Literal["local", "cloud", "hybrid"] = Field(
        default="local",
        description="Active inference execution mode"
    )
    
    # Model Architecture
    primary_llm: str = Field(
        default="qwen3.5:4b",
        description="Default local conversational generation model"
    )
    reasoning_llm: str = Field(
        default="qwen3.5:9b-q4_K_M",
        description="Heavy reasoning model for justified high-complexity tasks"
    )
    embedding_model: str = Field(
        default="Qwen3-Embedding-0.6B",
        description="Dense vector embedding model"
    )
    reranker_model: str = Field(
        default="Qwen3-Reranker-0.6B",
        description="Semantic reranking model"
    )
    asr_model: str = Field(
        default="faster-whisper-small-int8",
        description="Lightweight ASR model"
    )
    darija_asr_candidate: str = Field(
        default="atlasia/moulsot.v0.3",
        description="Moroccan Darija fine-tuned ASR model"
    )
    tts_fr_en: str = Field(
        default="Kokoro-82M",
        description="French and English TTS synthesizer"
    )
    tts_ar: str = Field(
        default="Piper-ar_JO",
        description="Modern Standard Arabic / Darija TTS synthesizer"
    )
    darija_lid: str = Field(
        default="atlasia/DarijaLID",
        description="Darija dialect language identification model"
    )
    arabizi_model: str = Field(
        default="atlasia/Transliteration-Moroccan-Darija",
        description="Arabizi Latin-to-Arabic transliteration model"
    )

    # Device Allocations (Preserve GPU exclusively for active LLM)
    primary_llm_device: str = "cuda"
    reasoning_llm_device: str = "cuda"
    embedding_device: str = "cpu"
    reranker_device: str = "cpu"
    asr_device: str = "cpu"
    tts_device: str = "cpu"

    # Hardware & Memory Guardrails
    max_gpu_vram_mb: int = Field(
        default=7000,
        description="Maximum permitted GPU VRAM allocation in MB (out of 8188 MB)"
    )
    max_system_ram_mb: int = Field(
        default=13500,
        description="Maximum permitted Host System RAM allocation in MB (out of 16000 MB)"
    )
    
    # Ollama endpoint
    ollama_base_url: str = "http://localhost:11434"

    # Optional Cloud API keys (disabled by default in local mode)
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""



ai_config = AIModelConfig()
