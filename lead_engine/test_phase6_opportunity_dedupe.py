from .dedupe import Dedupe

class DB:
    def __init__(self, rows):
        self.rows = rows
    def all_leads(self):
        return self.rows

def L(company, person, need, fp, qualified=True):
    return {"company": company, "person": person, "business_need": need, "fingerprint": fp, "qualified": qualified, "qualification_status": "qualified" if qualified else "in_review"}

def test_different_company_same_need_is_new_lead():
    assert Dedupe(DB([L("A", "Alex", "AI agents", "1")])).find_exact_duplicate(L("B", "Alex", "AI agents", "2")) is None

def test_same_company_different_person_same_need_is_new_lead():
    assert Dedupe(DB([L("A", "Alex", "AI agents", "1")])).find_exact_duplicate(L("A", "Jordan", "AI agents", "2")) is None

def test_same_company_same_person_different_need_is_new_lead():
    assert Dedupe(DB([L("A", "Alex", "AI agents", "1")])).find_exact_duplicate(L("A", "Alex", "mobile app", "2")) is None

def test_same_company_same_person_same_need_is_duplicate_only_after_qualification():
    existing = L("A", "Alex", "AI agents", "1")
    candidate = L("A", "Alex", "AI agents", "2", qualified=False)
    assert Dedupe(DB([existing])).find_exact_duplicate(candidate) is None
    candidate["qualified"] = True
    candidate["qualification_status"] = "qualified"
    assert Dedupe(DB([existing])).find_exact_duplicate(candidate) == existing

def test_missing_need_never_discards_lead():
    existing = L("A", "Alex", "", "1")
    candidate = L("A", "Alex", "", "2")
    assert Dedupe(DB([existing])).find_exact_duplicate(candidate) is None
