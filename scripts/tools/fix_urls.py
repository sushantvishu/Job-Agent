import re
import sys

filepath = 'd:/job-agent/app/job_collector.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Filter out search-results from discover_job_candidates
if 'is_non_job_content_url' in content:
    content = content.replace(
        'or "linkedin.com/school/" in lowered',
        'or "linkedin.com/school/" in lowered\n                or "linkedin.com/jobs/search-results/" in lowered'
    )

# Fix 2: Override discover_job_candidates to filter out bad URLs before returning
discover_def = """    def discover_job_candidates(self, page: Page, target_roles: list[str] | None = None, max_results: int = 15) -> list[dict[str, str]]:"""
new_discover_def = """    def discover_job_candidates(self, page: Page, target_roles: list[str] | None = None, max_results: int = 15) -> list[dict[str, str]]:
        candidates = self._raw_discover_job_candidates(page, target_roles, max_results)
        return [c for c in candidates if not self.is_non_job_content_url(c.get('url', ''))]

    def _raw_discover_job_candidates(self, page: Page, target_roles: list[str] | None = None, max_results: int = 15) -> list[dict[str, str]]:"""
content = content.replace(discover_def, new_discover_def)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("job_collector.py updated.")

