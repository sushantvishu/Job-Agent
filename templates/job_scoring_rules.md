# Job Scoring Rules

The agent scores each job from 0 to 100.

## Positive signals

- `+25` cybersecurity, VAPT, SOC, GRC, AppSec, API security, vulnerability assessment relevance
- `+20` any of: internship, intern, fresher, junior, associate, trainee, entry level, `0 years`, `0-1 year`, `1 year`, `up to 1 year`, `1-2 years` — these are ALL fully accepted, apply full bonus
- `+25` skill overlap with candidate profile (VAPT, Burp Suite, OWASP, Nmap, Python, Wireshark, SIEM, SOC, GRC, Kali Linux, Penetration Testing)
- `+10` location match (Bengaluru, Hyderabad, Pune, Delhi, Mumbai, Noida) or Remote
- `+10` legitimate company and normal application form
- `+10` learning scope through hands-on security work or mentoring

## Negative signals — EXPERIENCE

- `0` penalty for: internship, fresher, 0 years, 0-1 year, 1 year, up to 1 year, 1-2 years — DO NOT penalise these at all
- `-0` for `2 years` only — still acceptable, no penalty
- `-20` mandatory `3 years` experience
- `-35` mandatory `5+ years` experience
- `-100` fake experience or dishonest hiring flow

## Negative signals — OTHER

- `-40` sales, telecalling, senior, manager, director, VP, or non-technical support roles
- `-50` suspicious sensitive data request very early in the application
- `-30` job is clearly outside cybersecurity domain (e.g. retail, logistics, HR)

## CRITICAL RULE

**Never discard a job purely because it says internship, 0 years, 0-1 year, or 1 year of experience.**
These are exactly the target opportunities for this candidate.
If a job says "fresher" or "intern" and is in cybersecurity, the base score should be at least 60 before any penalties.

## Decision bands

- `80-100`: strong apply
- `65-79`: apply after review
- `50-64`: save only / ask user
- `0-49`: skip

## Hard safety stops

- Never automate login
- Never store passwords
- Never bypass CAPTCHA, OTP, phone verification, or email verification
- Never fake experience
- Never mass scrape LinkedIn
- Never auto-submit LinkedIn applications
- Always stop if unsure
