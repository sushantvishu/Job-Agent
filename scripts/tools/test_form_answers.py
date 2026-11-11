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

# Simulate real application page questions the bot encounters
profile_summary = (
    "Name: Jane Doe\n"
    "Experience: 1 year (projects, labs, internships)\n"
    "Skills: VAPT, Burp Suite, OWASP, Nmap, Python, Wireshark, SIEM, SOC, GRC, Kali Linux, Penetration Testing, OWASP Top 10\n"
    "Location: Bengaluru, India\n"
    "Preferred locations: Bengaluru, Hyderabad, Pune, Delhi, Mumbai, Noida, Remote\n"
    "Notice Period: Immediate\n"
    "Current CTC: Fresher (no current CTC)\n"
    "Expected Salary: As per company standards\n"
    "Education: B.Tech / B.E in Computer Science / Cybersecurity\n"
    "Custom answers:\n"
    "  - work authorization: Authorized to work in India.\n"
    "  - willing to relocate: Yes, willing to relocate to Bengaluru, Hyderabad, Pune, Delhi, Mumbai, Noida or work remotely.\n"
    "  - night shifts: Open to discuss shift requirements based on job needs.\n"
    "  - why cybersecurity: Passionate about cybersecurity since college; enjoy finding vulnerabilities, "
    "CTF challenges, and protecting systems from real-world threats.\n"
    "  - current CTC: Fresher, no current salary.\n"
    "  - expected CTC: As per company standards / industry norms for the role.\n"
)

questions = [
    "How many years of experience do you have in VAPT?",
    "Are you willing to relocate?",
    "What is your current CTC?",
    "Describe your experience with Burp Suite.",
    "Are you comfortable working night shifts?",
    "What is your expected CTC in LPA?",
    "Do you have experience with OWASP Top 10?",
    "What is your notice period?",
    "Why are you interested in cybersecurity?",
    "Which tools have you used for penetration testing?",
]

print("Testing model answering form questions from application pages\n")
print("=" * 60)

for q in questions:
    prompt = (
        f"You are filling a job application form on behalf of a candidate.\n\n"
        f"Candidate profile:\n{profile_summary}\n"
        f"Form question: {q}\n\n"
        f"Give a short, honest, professional answer (1-2 sentences max). "
        f"Only answer what is true based on the profile. Do not invent facts."
    )
    try:
        answer = client.generate(prompt)
        print(f"Q: {q}")
        print(f"A: {answer}")
        print()
    except Exception as e:
        print(f"Q: {q}")
        print(f"FAILED: {e}")
        print()

