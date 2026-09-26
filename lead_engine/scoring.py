from typing import Dict


SIGNAL_WEIGHTS = {
    "individual developer": 8,
    "software engineer": 7,
    "software developer": 7,
    "developer": 6,
    "engineering hire": 7,
    "engineering hiring": 7,
    "contract developer": 8,
    "contract engineer": 8,
    "freelance developer": 7,
    "developer contractor": 8,
    "technical contractor": 7,
    "engineering contractor": 7,
    "technology recruitment": 9,
    "tech recruitment": 9,
    "it recruitment": 9,
    "technical recruitment": 9,
    "technology staffing": 9,
    "it staffing": 9,
    "technical staffing": 9,
    "engineering recruitment": 8,
    "engineering staffing": 8,
    "technology talent acquisition": 8,
    "it talent acquisition": 8,
    "remote software engineer": 8,
    "remote software developer": 8,
    "remote developer": 8,
    "remote engineer": 7,
    "remote engineering": 7,
    "remote product designer": 8,
    "remote designer": 7,
    "remote product manager": 8,
    "remote data scientist": 8,
    "remote data analyst": 8,
    "remote data engineer": 8,
    "remote machine learning": 8,
    "remote ml engineer": 8,
    "remote ai engineer": 8,
    "remote technology role": 8,
    "remote tech role": 8,
    "remote technical role": 8,
    "remote-first hiring": 7,
    "remote hiring": 6,
    "work-from-home technology role": 8,
    "distributed engineering": 7,
    "distributed development": 7,
    "remote engineering position": 8,
    "remote engineering role": 8,
}

ROUTE_SIGNAL_WEIGHTS = {
    "Shiftr": {
        "individual developer": 8, "software engineer": 7, "software developer": 7,
        "developer": 6, "engineering hire": 7, "engineering hiring": 7,
        "contract developer": 8, "contract engineer": 8, "freelance developer": 7,
        "developer contractor": 8, "technical contractor": 7, "engineering contractor": 7,
        "software development": 7, "development team": 7, "engineering team": 7,
        "development contractor": 8, "software contractor": 8, "technical talent": 6,
        "engineering talent": 6, "developer talent": 6, "staff augmentation": 8,
        "outsourcing": 7, "development team hiring": 8, "ai development": 7,
        "ai engineer": 7, "llm": 6, "llm integration": 8, "ai agent": 7,
        "ai agents": 7, "mobile development": 7, "mobile developer": 7,
        "mobile engineer": 7, "saas development": 7, "enterprise software development": 7,
    },
    "Paxus": {
        "technology recruitment": 9, "tech recruitment": 9, "it recruitment": 9,
        "technical recruitment": 9, "technology staffing": 9, "it staffing": 9,
        "technical staffing": 9, "engineering recruitment": 8, "engineering staffing": 8,
        "technology talent acquisition": 8, "it talent acquisition": 8,
        "recruiting engineers": 8, "staffing engineers": 8, "recruiting developers": 8,
        "staffing developers": 8, "technology recruiting": 9, "technical recruiting": 9,
        "engineering recruiting": 8, "technology hiring support": 8,
        "technical hiring support": 8, "engineering hiring support": 8,
        "recruitment support": 8, "staffing support": 8,
        "talent acquisition support": 8, "recruiting support": 8,
    },
    "Thorio": {
        "remote software engineer": 8, "remote software developer": 8, "remote developer": 8,
        "remote engineer": 7, "remote engineering": 7, "remote product designer": 8,
        "remote designer": 7, "remote product manager": 8, "remote data scientist": 8,
        "remote data analyst": 8, "remote data engineer": 8, "remote machine learning": 8,
        "remote ml engineer": 8, "remote ai engineer": 8, "remote technology role": 8,
        "remote tech role": 8, "remote technical role": 8, "remote-first hiring": 7,
        "remote hiring": 6, "work-from-home technology role": 8,
        "distributed engineering": 7, "distributed development": 7,
        "remote engineering position": 8, "remote engineering role": 8,
        "remote data": 7, "remote ai": 7, "remote product": 7, "remote design": 7,
        "remote ux": 7, "remote ui": 7, "remote web": 7, "remote technical": 7,
    },
    "Astrivon Labs": {
        "looking for a dev agency": 10, "looking for a tech partner": 10,
        "need an mvp built": 10, "mvp built for my startup": 10,
        "b2b outreach expert": 9, "b2b sales representative": 9,
        "lead generation specialist": 9, "sales automation expert": 9,
        "ai/ml developer": 9, "computer vision specialist": 9,
        "automate business workflow": 9, "crm automation": 8,
        "full-stack software engineer": 8, "scaling my web/mobile app": 9,
        "raised seed funding": 7, "seed funding": 6,
        "non-technical founder": 7, "outsource sales pipeline": 8,
        "reduce in-house dev costs": 7, "reduce in-house sales costs": 7,
        "dev agency": 8, "tech partner": 8, "mvp": 8, "b2b outreach": 8,
        "b2b sales": 8, "lead generation": 8, "sales automation": 8,
        "computer vision": 8, "business workflow": 7, "crm": 6,
        "software development": 6, "product development": 7, "web/mobile app": 7,
    },
}

ROUTE_BONUSES = {
    "Shiftr": {"developer": 3, "engineer": 3, "contract": 3, "freelance": 3},
    "Paxus": {"recruitment": 4, "staffing": 4, "talent acquisition": 3},
    "Thorio": {"remote": 4, "distributed": 3, "work-from-home": 4, "remote-first": 4},
    "Astrivon Labs": {"mvp": 3, "automation": 3, "ai": 2, "b2b": 3, "agency": 3},
}


def _build_text(company: str, signal: str, evidence: str) -> str:
    return " ".join([company or "", signal or "", evidence or ""]).lower()


def score_lead(company: str, signal: str, evidence: str) -> int:
    text = _build_text(company, signal, evidence)
    return sum(weight for phrase, weight in SIGNAL_WEIGHTS.items() if phrase in text)


def score_route(route: str, company: str, signal: str, evidence: str) -> int:
    text = _build_text(company, signal, evidence)
    route_signals = ROUTE_SIGNAL_WEIGHTS.get(route, {})
    score = sum(weight for phrase, weight in route_signals.items() if phrase in text)
    bonuses = ROUTE_BONUSES.get(route, {})
    score += sum(weight for phrase, weight in bonuses.items() if phrase in text)
    return score


def priority_from_score(score: int) -> str:
    if score >= 20:
        return "Critical"
    if score >= 12:
        return "High"
    if score >= 6:
        return "Medium"
    if score > 0:
        return "Low"
    return "Review"


def score_result(company: str, signal: str, evidence: str) -> Dict[str, object]:
    score = score_lead(company, signal, evidence)
    return {"lead_score": score, "priority": priority_from_score(score)}


def route_score_result(route: str, company: str, signal: str, evidence: str) -> Dict[str, object]:
    score = score_route(route, company, signal, evidence)
    return {"route": route, "route_score": score, "priority": priority_from_score(score)}


if __name__ == "__main__":
    print(score_result("Acme", "remote software engineer", "Acme is hiring a remote software engineer."))
