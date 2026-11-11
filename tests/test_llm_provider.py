from app.llm import LLMProvider, OpenAICompatibleProvider
from app.ollama_client import OllamaClient


def test_llm_provider_inheritance():
    assert issubclass(OllamaClient, LLMProvider)
    assert issubclass(OpenAICompatibleProvider, LLMProvider)


def test_cloud_provider_mock():
    provider = OpenAICompatibleProvider(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="",  # empty
        model="gemini-2.0-flash",
    )
    # With empty api_key, is_available is False and generate returns empty safely
    assert not provider.is_available()
    assert provider.generate("hello") == ""
