// Typst ATS-Optimized Master Resume Template
#set page(
  paper: "a4",
  margin: (x: 1.5cm, top: 1.5cm, bottom: 1.5cm),
)
#set text(
  font: "Liberation Sans",
  size: 10pt,
  fill: rgb("#111827"),
)
#set par(justify: true, leading: 0.55em)

// Header
#align(center)[
  #text(size: 18pt, weight: "bold")[{{ name }}] \
  #v(2pt)
  #text(size: 10pt, fill: rgb("#4b5563"))[
    {{ location }} | {{ phone }} | {{ email }} | #link("{{ linkedin }}")[LinkedIn] | #link("{{ github }}")[GitHub]
  ] \
  #v(2pt)
  #text(size: 11pt, weight: "medium", fill: rgb("#0369a1"))[{{ headline }}]
]

#v(8pt)
#line(length: 100%, stroke: 0.75pt + rgb("#cbd5e1"))

// Professional Summary
#v(4pt)
== Professional Summary
#v(2pt)
{{ summary }}

// Core Technical Skills
#v(6pt)
== Core Technical Competencies
#v(2pt)
#grid(
  columns: (1fr, 1fr),
  gutter: 12pt,
  [
    *Security & Testing:* {{ security_skills }} \
    *Offensive Methodologies:* OWASP Top 10, Network Scanning, Reconnaissance
  ],
  [
    *Languages & Tooling:* {{ dev_skills }} \
    *Platforms & Systems:* Linux (Kali/Ubuntu), Docker, Git, REST APIs
  ]
)

// Experience & Projects
#v(6pt)
== Hands-On Experience & Key Projects
#v(2pt)
*Cybersecurity & Security Automation Practitioner* #h(1fr) *2024 -- Present* \
#text(fill: rgb("#4b5563"), style: "italic")[Independent Security Research & Autonomous Tooling]
- Conducted vulnerability assessment and penetration testing across web applications against OWASP Top 10 vulnerabilities (SQLi, XSS, SSRF, IDOR).
- Designed and authored high-performance security automation pipelines in Python, utilizing asynchronous networking and Playwright for headless verification.
- Executed network reconnaissance and vulnerability scanning using Burp Suite, Nmap, Wireshark, and Nessus.
- Triaged and mapped incident vectors using SIEM (Splunk) workflows, log forensics, and the MITRE ATT&CK enterprise matrix.

// Education & Credentials
#v(6pt)
== Education & Academic Credentials
#v(2pt)
*{{ highest_degree }}* #h(1fr) *Graduation: {{ graduation_year }}* \
#text(fill: rgb("#4b5563"))[Specialization in {{ field_of_study }}]
