import sys
sys.path.insert(0, 'd:/job-agent')
from app.ollama_client import OllamaClient
from app.config import load_config
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('test')
config = load_config()

client = OllamaClient(
    base_url=config.ollama_base_url,
    model=config.ollama_model,
    logger=logger,
    fallback_models=config.fallback_models,
)

print(f'Testing model: {config.ollama_model}')
print(f'Base URL: {config.ollama_base_url}')
print()

test_prompt = (
    "Score this job for a fresher cybersecurity candidate (0-1 year experience) with VAPT, Burp Suite, OWASP, Python skills.\n\n"
    "Job: VAPT Analyst at Mintopps\n"
    "Experience: 0-2 years\n"
    "Skills required: Burp Suite, OWASP, Python, vulnerability assessment\n"
    "Location: Hyderabad\n\n"
    'Reply with JSON: {"score": <0-100>, "reason": "<short reason>"}'
)

try:
    result = client.generate(test_prompt)
    print('SUCCESS! Model responded:')
    print(result)
except Exception as e:
    print(f'FAILED: {e}')

