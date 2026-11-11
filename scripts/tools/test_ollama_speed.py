import time
from app.main import build_runtime
from app.utils import JobPosting, ProfileData

config, logger, tracker, profile, collector, matcher, filler, exporter = build_runtime()

job = JobPosting(
    url="http://test",
    source="test",
    title="Security Analyst",
    company="TestCorp",
    description="We are looking for a security analyst with VAPT experience. Must have 1 year of experience." * 20
)

start = time.time()
print("Testing generate_application_material...")
mat = filler.ollama_client.generate_application_material(job, profile)
print(f"Time taken: {time.time() - start:.2f} seconds")
print(f"Result keys: {mat.keys()}")
print(f"Used fallback? {mat.get('used_fallback')}")

