import json

with open('d:/job-agent/profile/profile.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Update the summary with strong anti-plagiarism guidelines for the AI
data['summary'] = (
    "Cybersecurity-focused fresher with hands-on practice in web application testing, vulnerability assessment, "
    "API testing, and SOC workflows. "
    "\n\n[AI/LLM Persona Guidelines]: When generating cover letters, summaries, or long-form answers on my behalf, "
    "YOU MUST BE HIGHLY AUTHENTIC. Do NOT use generic, plagiarized-sounding buzzwords (e.g., 'I am highly motivated', 'As a dynamic professional', 'In today's fast-paced world'). "
    "Write exactly as a concise, straight-to-the-point engineer. Use my specific listed skills (Burp Suite, OWASP, etc.) in concrete contexts. "
    "Never hallucinate experience I do not have (I have exactly 1.0 years of experience). Keep it human, slightly casual but professional, and 100% original."
)

with open('d:/job-agent/profile/profile.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Profile patched!")
