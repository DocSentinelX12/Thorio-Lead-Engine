import re
from typing import Dict, List


ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
    "Astrivon Labs",
)

HIRING_CONTEXT = (
    r"\bhir(?:e|ing|ed|es)\b|\brecruit(?:ment|ing|ed|er|ers)?\b|\bstaff(?:ing|ed|er|ers)?\b|\bopening\b|\bposition\b|\brole\b|\bvacanc(?:y|ies)\b|\bjob(?:s)?\b|\bopportunit(?:y|ies)\b|\bseeking\b|\blooking for\b|\bjoin our team\b|\bjoin the team\b|\bwe(?:'re| are) hiring\b"
)

JOB_ROLE_CONTEXT = (
    r"\bsoftware engineer\b|\bsoftware developer\b|\bsoftware development engineer\b|\bfull[- ]stack engineer\b|\bfull[- ]stack developer\b|\bfrontend engineer\b|\bfrontend developer\b|\bbackend engineer\b|\bbackend developer\b|\bweb developer\b|\bweb engineer\b|\bapplication developer\b|\bapplication engineer\b|\bmobile developer\b|\bmobile engineer\b|\bdevops engineer\b|\bplatform engineer\b|\bcloud engineer\b|\bdata engineer\b|\bdata scientist\b|\bdata analyst\b|\bmachine learning engineer\b|\bmachine learning developer\b|\bml engineer\b|\bai engineer\b|\bai developer\b|\bcomputer vision engineer\b|\bcomputer vision developer\b|\bproduct manager\b|\bproduct designer\b|\bux designer\b|\bui designer\b|\btechnical writer\b|\bvideo editor\b|\bcontent creator\b|\btechnical artist\b|\b3d artist\b|\b2d animator\b|\bgraphics engineer\b|\bcreator technology\b|\btechnical support\b|\bit support\b|\btechnology consultant\b"
)

SHIFTR_RULES = [
    r"\bindividual developer\b", r"\bsoftware engineer\b", r"\bsoftware developer\b", r"\bsoftware development engineer\b", r"\bdeveloper\b", r"\bengineering hire\b", r"\bengineering hiring\b", r"\bcontract developer\b", r"\bcontract engineer\b", r"\bfreelance developer\b", r"\bindividual engineer\b", r"\bdeveloper contractor\b", r"\bsoftware development contractor\b", r"\btechnical contractor\b", r"\bengineering contractor\b", r"\bdevelopment team hiring\b", r"\bdevelopment contractor\b", r"\bsoftware contractor\b", r"\bengineering talent\b", r"\bdeveloper talent\b", r"\btechnical talent\b", r"\bengineering team\b", r"\bsoftware development team\b", r"\bai development\b", r"\bai engineer\b", r"\bai developer\b", r"\bai agent(?:s)?\b", r"\bai agent development\b", r"\bllm\b", r"\bllm integration\b", r"\bmobile development\b", r"\bmobile developer\b", r"\bmobile engineer\b", r"\bsaas development\b", r"\benterprise software development\b", r"\bsoftware development\b", r"\bdevelopment team\b", r"\bstaff augmentation\b", r"\boutsourcing\b",
]

PAXUS_RULES = [
    r"\btechnology recruitment\b", r"\btech recruitment\b", r"\bit recruitment\b", r"\btechnical recruitment\b", r"\btechnology staffing\b", r"\bit staffing\b", r"\btechnical staffing\b", r"\bengineering recruitment\b", r"\bengineering staffing\b", r"\btechnology talent acquisition\b", r"\bit talent acquisition\b", r"\brecruiting technology professionals\b", r"\bstaffing technology professionals\b", r"\brecruiting technical professionals\b", r"\bstaffing technical professionals\b", r"\brecruiting engineers\b", r"\bstaffing engineers\b", r"\brecruiting developers\b", r"\bstaffing developers\b", r"\btechnology recruiting\b", r"\btechnical recruiting\b", r"\bengineering recruiting\b", r"\btechnology hiring support\b", r"\btechnical hiring support\b", r"\bengineering hiring support\b", r"\brecruitment support\b", r"\bstaffing support\b", r"\btalent acquisition support\b", r"\brecruiting support\b",
]

THORIO_REMOTE_RULES = [
    r"\bremote\b", r"\bremote[- ]first\b", r"\bfully remote\b", r"\b100% remote\b", r"\bremote only\b", r"\bremote position\b", r"\bremote role\b", r"\bremote job\b", r"\bremote opportunity\b", r"\bremote opening\b", r"\bremote hiring\b", r"\bremote engineer\b", r"\bremote developer\b", r"\bremote software\b", r"\bremote engineering\b", r"\bremote technology\b", r"\bremote tech\b", r"\bremote technical\b", r"\bremote data\b", r"\bremote ai\b", r"\bremote machine learning\b", r"\bremote product\b", r"\bremote design\b", r"\bremote designer\b", r"\bremote ux\b", r"\bremote ui\b", r"\bremote web\b", r"\bremote video\b", r"\bremote content\b", r"\bremote creator\b", r"\bremote youtube\b", r"\bremote animation\b", r"\bremote animator\b", r"\bremote cartoon\b", r"\bremote vfx\b", r"\bremote visual effects\b", r"\bremote 3d\b", r"\bremote 2d\b", r"\bremote motion graphics\b", r"\bremote technical artist\b", r"\bremote technical designer\b", r"\bremote web designer\b", r"\bremote video editor\b", r"\bremote video producer\b", r"\bremote content creator\b", r"\bremote content producer\b", r"\bremote youtube producer\b", r"\bremote youtube editor\b", r"\bremote animation artist\b", r"\bremote technical animator\b", r"\bremote virtual production\b", r"\bremote film\b", r"\bremote media\b", r"\bremote entertainment technology\b", r"\bwork[- ]from[- ]home\b", r"\bwork from home\b", r"\bdistributed team\b", r"\bdistributed engineering\b", r"\bdistributed development\b", r"\bdistributed workforce\b", r"\banywhere in the us\b", r"\bwork from anywhere\b",
]

NON_REMOTE_CONTEXT = [r"\bon[- ]site\b", r"\bonsite\b", r"\bin[- ]office\b", r"\boffice[- ]based\b", r"\bhybrid\b", r"\bhybrid[- ]remote\b", r"\bremote[- ]hybrid\b"]


def _text(company: str, signal: str, evidence: str) -> str:
    return " ".join([company or "", signal or "", evidence or ""]).lower()


def _has_hiring_context(text: str) -> bool:
    return bool(re.search(HIRING_CONTEXT, text, re.IGNORECASE))


def _has_job_role_context(text: str) -> bool:
    return bool(re.search(JOB_ROLE_CONTEXT, text, re.IGNORECASE))


def _has_astrivon_context(text: str) -> bool:
    patterns = (
        r"\bdev agency\b", r"\btech partner\b", r"\bmvp\b", r"\bai/ml\b", r"\bai developer\b", r"\bmachine learning\b", r"\bfull[- ]stack software engineer\b", r"\bscaling my web/mobile app\b", r"\bneed help scaling\b", r"\bb2b outreach\b",
        r"\bb2b sales\b", r"\blead generation\b", r"\blead generation specialist\b", r"\bsales representative\b", r"\bsales automation\b", r"\bsales automation expert\b",
        r"\bcomputer vision\b", r"\bcrm\b", r"\bcrm automation\b", r"\bautomate business workflow\b",
        r"\bseed funding\b", r"\braised seed funding\b", r"\bnon-technical founder\b",
        r"\bweb/mobile app\b", r"\bsoftware development\b", r"\bproduct development\b",
        r"\boutsource sales pipeline\b", r"\breduce in-house dev costs\b", r"\breduce in-house sales costs\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _matches_rules(text: str, rules: List[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in rules)


def score_routes(company: str, signal: str, evidence: str) -> Dict[str, int]:
    from .scoring import score_route
    return {route: score_route(route, company, signal, evidence) for route in ROUTES}


def potential_routes(company: str, signal: str, evidence: str) -> List[str]:
    text = _text(company, signal, evidence)
    scores = score_routes(company, signal, evidence)
    routes: List[str] = []
    if _matches_rules(text, SHIFTR_RULES) and (_has_hiring_context(text) or _has_job_role_context(text)):
        routes.append("Shiftr")
    if _matches_rules(text, PAXUS_RULES) and _has_hiring_context(text):
        routes.append("Paxus")
    if _matches_rules(text, THORIO_REMOTE_RULES) and not _matches_rules(text, NON_REMOTE_CONTEXT):
        routes.append("Thorio")
    if _has_astrivon_context(text):
        routes.append("Astrivon Labs")
    return [route for route in ROUTES if route in routes and scores.get(route, 0) > 0]


def route(company: str, signal: str, evidence: str) -> str:
    scores = score_routes(company, signal, evidence)
    routes = potential_routes(company, signal, evidence)
    if not routes:
        return "Review"
    return max(routes, key=lambda name: (scores.get(name, 0), -ROUTES.index(name)))
