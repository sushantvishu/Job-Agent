import json

with open('d:/job-agent/profile/profile.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Update custom answers
data['custom_answers'].update({
    "current ctc": "Fresher, currently 0 LPA.",
    "current salary": "Fresher, currently 0 LPA.",
    "expected ctc": "Expected CTC is between 4 LPA to 6 LPA (negotiable based on benefits).",
    "expected salary": "Expected salary is between 4 LPA to 6 LPA.",
    "relocation": "Yes, I am fully open to relocating for this role. I prefer Bengaluru, Hyderabad, Pune, Delhi, Mumbai, or Noida, but I am open to discussing other locations if the role is a strong fit.",
    "notice period": "I am an immediate joiner with a 0-day notice period.",
    "availability": "I am available to join immediately.",
    "strengths": "My primary strengths are in VAPT, Burp Suite, and OWASP methodologies. I am a fast learner and have hands-on experience in vulnerability assessment.",
    "weaknesses": "I am a fresher, so I lack enterprise-level corporate experience, but I make up for it with intensive hands-on lab training and CTF challenges."
})

with open('d:/job-agent/profile/profile.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Profile answers patched!")
