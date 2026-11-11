import os
import re

log_path = r"C:\Users\susha\.gemini\antigravity\brain\10b67163-01fa-4ff9-81fc-4ffc83ff07fa\.system_generated\tasks\task-3667.log"

print("=" * 60)
print("INSPECTING RECENT FORM FILLING EVENTS IN TASK-3667 LOG")
print("=" * 60)

if not os.path.exists(log_path):
    print(f"Log not found at {log_path}")
    exit(1)

with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

print(f"Total lines in log: {len(lines)}")

# Search for form filling entries
patterns = [
    re.compile(r"Filled field|Entering text|Selecting option|Answered|Uploading resume|resume_path|Uploaded|OTP|Form filled|Field matched", re.IGNORECASE),
    re.compile(r"Applied to|Successfully applied|Application submitted|Submit clicked|Submitted", re.IGNORECASE)
]

matched_fill_lines = []
matched_submit_lines = []

for line in lines[-2000:]: # last 2000 lines
    if any(p.search(line) for p in patterns[:1]):
        matched_fill_lines.append(line.strip())
    if any(p.search(line) for p in patterns[1:]):
        matched_submit_lines.append(line.strip())

print(f"\nFound {len(matched_fill_lines)} form field interactions in recent 2000 lines:")
for l in matched_fill_lines[-25:]:
    print("  ", l)

print(f"\nFound {len(matched_submit_lines)} submit/apply events in recent 2000 lines:")
for l in matched_submit_lines[-25:]:
    print("  ", l)

