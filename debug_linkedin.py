import ssl, urllib3, requests as _req
urllib3.disable_warnings()
ssl._create_default_https_context = ssl._create_unverified_context
_orig = _req.Session.request
def _nv(self, method, url, **kw):
    kw.setdefault("verify", False)
    return _orig(self, method, url, **kw)
_req.Session.request = _nv

from linkedin_api import Linkedin
from config import LINKEDIN_EMAIL, LINKEDIN_PASSWORD

api = Linkedin(LINKEDIN_EMAIL, LINKEDIN_PASSWORD)
jobs = api.search_jobs(keywords="QA", location_name="Dallas-Fort Worth Metroplex", listed_at=86400, limit=10)
print(f"Found {len(jobs)} jobs — checking full detail for Easy Apply...\n")

easy = 0
for j in jobs[:10]:
    jid = j.get("entityUrn", "").split(":")[-1]
    title = j.get("title", "")
    detail = api.get_job(jid)
    apply_method = detail.get("applyMethod", {})
    is_easy = isinstance(apply_method, dict) and any("ComplexOnsiteApply" in k for k in apply_method)
    count = detail.get("applies") or detail.get("numApplicants") or 0
    if is_easy:
        easy += 1
    print(f"{'[EASY]' if is_easy else '[EXT] '} {title} | applicants={count} | applyMethod keys={list(apply_method.keys()) if isinstance(apply_method, dict) else apply_method}")

print(f"\nEasy Apply: {easy}/{len(jobs[:10])}")
