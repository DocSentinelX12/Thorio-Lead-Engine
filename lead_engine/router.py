import re
from typing import Dict, List


ROUTES = (
    "Shiftr",
    "Paxus",
    "Thorio",
)


HIRING_CONTEXT = (
    r"\bhir(?:e|ing|ed|es)\b"
    r"|\brecruit(?:ment|ing|ed|er|ers)?\b"
    r"|\bstaff(?:ing|ed|er|ers)?\b"
    r"|\bopening\b"
    r"|\bposition\b"
    r"|\brole\b"
    r"|\bvacanc(?:y|ies)\b"
    r"|\bjob(?:s)?\b"
    r"|\bopportunit(?:y|ies)\b"
    r"|\bseeking\b"
    r"|\blooking for\b"
    r"|\bjoin our team\b"
    r"|\bjoin the team\b"
    r"|\bwe(?:'re| are) hiring\b"
)


JOB_ROLE_CONTEXT = (
    r"\bsoftware engineer\b|\bsoftware developer\b|\bsoftware development engineer\b"
    r"|\bfull[- ]stack engineer\b|\bfull[- ]stack developer\b"
    r"|\bfrontend engineer\b|\bfront[- ]end engineer\b|\bfrontend developer\b|\bfront[- ]end developer\b"
    r"|\bbackend engineer\b|\bback[- ]end engineer\b|\bbackend developer\b|\bback[- ]end developer\b"
    r"|\bweb developer\b|\bweb engineer\b|\bapplication developer\b|\bapplication engineer\b"
    r"|\bmobile developer\b|\bmobile engineer\b|\bios developer\b|\bios engineer\b|\bandroid developer\b|\bandroid engineer\b"
    r"|\bembedded software engineer\b|\bembedded engineer\b|\bfirmware engineer\b|\bsystems engineer\b"
    r"|\bsoftware architect\b|\bsoftware development\b"
    r"|\bdevops engineer\b|\bdevops developer\b|\bdevsecops engineer\b|\bsite reliability engineer\b|\bsre\b"
    r"|\bplatform engineer\b|\bplatform developer\b|\bcloud engineer\b|\bcloud developer\b|\bcloud architect\b"
    r"|\binfrastructure engineer\b|\binfrastructure developer\b|\bnetwork engineer\b|\bnetwork administrator\b"
    r"|\bsystems administrator\b|\bdatabase administrator\b|\bdatabase engineer\b|\bsolutions architect\b|\bsolutions engineer\b"
    r"|\btechnical architect\b|\bsite reliability\b"
    r"|\bdata engineer\b|\bdata scientist\b|\bdata analyst\b|\bdata architect\b|\bdata developer\b"
    r"|\bmachine learning engineer\b|\bmachine learning developer\b|\bmachine learning researcher\b|\bml engineer\b|\bmlops engineer\b|\bmlops\b"
    r"|\bai engineer\b|\bai developer\b|\bartificial intelligence engineer\b|\bartificial intelligence developer\b|\bai researcher\b"
    r"|\bdeep learning engineer\b|\bnlp engineer\b|\bnatural language processing engineer\b|\bcomputer vision engineer\b|\bcomputer vision developer\b"
    r"|\bprompt engineer\b|\bresearch engineer\b|\bdata science\b"
    r"|\bcybersecurity engineer\b|\bcyber security engineer\b|\bsecurity engineer\b|\binformation security engineer\b|\bsecurity analyst\b"
    r"|\bsecurity architect\b|\bsecurity researcher\b|\bpenetration tester\b|\bpenetration testing\b|\bcloud security engineer\b"
    r"|\bapplication security engineer\b|\bsecurity operations\b|\bsoc analyst\b"
    r"|\bqa engineer\b|\bquality assurance engineer\b|\btest engineer\b|\bsoftware tester\b|\bautomation engineer\b"
    r"|\btest automation engineer\b|\bquality engineer\b|\bqa automation\b"
    r"|\bproduct manager\b|\btechnical product manager\b|\bproduct designer\b|\bproduct design\b|\bux designer\b|\bux engineer\b"
    r"|\bui designer\b|\bui engineer\b|\bweb designer\b|\bweb design\b|\btechnical designer\b|\binteraction designer\b"
    r"|\bexperience designer\b|\bdigital designer\b|\bdesign technologist\b|\bcreative technologist\b|\bvisual designer\b|\bgraphic designer\b|\bdigital product designer\b"
    r"|\bdeveloper advocate\b|\bdeveloper advocacy\b|\bdeveloper relations\b|\bdevrel\b|\btechnical evangelist\b"
    r"|\btechnical writer\b|\btechnical writing\b|\bdeveloper writer\b|\btechnical content creator\b|\btechnology content creator\b|\btech content creator\b"
    r"|\bdeveloper content creator\b|\btechnical content producer\b|\btechnology content producer\b|\btech content producer\b|\btechnical content\b|\btechnology content\b|\bdeveloper content\b"
    r"|\bvideo editor\b|\bvideo editing\b|\bvideo producer\b|\bvideo production\b|\bdigital video producer\b|\bdigital media producer\b"
    r"|\bcontent producer\b|\bdigital content producer\b|\bmedia producer\b|\bmultimedia producer\b|\bmultimedia designer\b|\bmotion designer\b"
    r"|\bmotion graphics designer\b|\bmotion graphics artist\b|\bmotion graphics\b|\bpost[- ]production editor\b|\bpost[- ]production\b|\bvideo production specialist\b|\bdigital media specialist\b"
    r"|\btechnical artist\b|\btechnical art\b|\btechnical animator\b|\b3d artist\b|\b3d animator\b|\b3d animation\b|\b2d animator\b|\b2d animation\b"
    r"|\bcharacter animator\b|\bcharacter animation\b|\banimation artist\b|\banimation engineer\b|\banimation developer\b|\banimation technical director\b|\btechnical director\b"
    r"|\brigging artist\b|\brigger\b|\bcharacter rigger\b|\b3d modeler\b|\b3d modeller\b|\b3d modeling\b|\b3d modelling\b"
    r"|\benvironment artist\b|\bconcept artist\b|\bvisual development artist\b|\bvisual effects artist\b|\bvfx artist\b|\bvfx compositor\b|\bcompositor\b"
    r"|\bvisual effects\b|\bcomputer graphics\b|\bcg artist\b|\bcg generalist\b|\blook development artist\b|\blighting artist\b|\bshader artist\b"
    r"|\brendering engineer\b|\brendering developer\b|\bgraphics engineer\b|\bgraphics programmer\b|\btechnical animation\b|\bcartoon animator\b|\bcartoon animation\b"
    r"|\bcharacter designer\b|\bstoryboard artist\b|\bstoryboard designer\b"
    r"|\bvirtual production\b|\bvirtual production artist\b|\bvirtual production engineer\b|\bvirtual production technician\b"
    r"|\bfilm technology\b|\bfilm production technology\b|\bdigital production\b|\bdigital production artist\b|\bpost[- ]production technology\b"
    r"|\bvideo technology\b|\bmedia technology\b|\bentertainment technology\b|\bstreaming technology\b|\bstreaming producer\b|\bvirtual production technology\b"
    r"|\byoutube producer\b|\byoutube editor\b|\byoutube content creator\b|\byoutube creator\b|\byoutube video editor\b|\byoutube production\b"
    r"|\bcreator producer\b|\bcreator operations\b|\bcreator technology\b|\bcreator tools\b|\bcreator economy\b|\bcontent technology\b|\bcontent operations\b|\bcontent production\b"
    r"|\bdigital creator\b|\bcontent creator\b"
    r"|\btechnical support engineer\b|\btechnical support specialist\b|\btechnical support\b|\bit support\b|\bit specialist\b|\bit engineer\b"
    r"|\binformation technology\b|\btechnology consultant\b|\btechnical consultant\b|\btechnology professional\b|\btechnical professional\b"
)


SHIFTR_RULES = [
    r"\bindividual developer\b", r"\bsoftware engineer\b", r"\bsoftware developer\b",
    r"\bsoftware development engineer\b", r"\bdeveloper\b", r"\bengineering hire\b",
    r"\bengineering hiring\b", r"\bcontract developer\b", r"\bcontract engineer\b",
    r"\bfreelance developer\b", r"\bindividual engineer\b", r"\bdeveloper contractor\b",
    r"\bsoftware development contractor\b", r"\btechnical contractor\b", r"\bengineering contractor\b",
    r"\bdevelopment team hiring\b", r"\bdevelopment contractor\b", r"\bsoftware contractor\b",
    r"\bengineering talent\b", r"\bdeveloper talent\b", r"\btechnical talent\b",
    r"\bengineering team\b", r"\bsoftware development team\b",
]


PAXUS_RULES = [
    r"\btechnology recruitment\b", r"\btech recruitment\b", r"\bit recruitment\b",
    r"\btechnical recruitment\b", r"\btechnology staffing\b", r"\bit staffing\b",
    r"\btechnical staffing\b", r"\bengineering recruitment\b", r"\bengineering staffing\b",
    r"\btechnology talent acquisition\b", r"\bit talent acquisition\b",
    r"\brecruiting technology professionals\b", r"\bstaffing technology professionals\b",
    r"\brecruiting technical professionals\b", r"\bstaffing technical professionals\b",
    r"\brecruiting engineers\b", r"\bstaffing engineers\b", r"\brecruiting developers\b",
    r"\bstaffing developers\b", r"\btechnology recruiting\b", r"\btechnical recruiting\b",
    r"\bengineering recruiting\b", r"\btechnology hiring support\b", r"\btechnical hiring support\b",
    r"\bengineering hiring support\b", r"\brecruitment support\b", r"\bstaffing support\b",
    r"\btalent acquisition support\b", r"\brecruiting support\b",
]


THORIO_REMOTE_RULES = [
    r"\bremote\b", r"\bremote[- ]first\b", r"\bfully remote\b", r"\b100% remote\b",
    r"\bremote only\b", r"\bremote position\b", r"\bremote role\b", r"\bremote job\b",
    r"\bremote opportunity\b", r"\bremote opening\b", r"\bremote hiring\b", r"\bremote engineer\b",
    r"\bremote developer\b", r"\bremote software\b", r"\bremote engineering\b", r"\bremote technology\b",
    r"\bremote tech\b", r"\bremote technical\b", r"\bremote data\b", r"\bremote ai\b",
    r"\bremote machine learning\b", r"\bremote product\b", r"\bremote design\b", r"\bremote designer\b",
    r"\bremote ux\b", r"\bremote ui\b", r"\bremote web\b", r"\bremote video\b", r"\bremote content\b",
    r"\bremote creator\b", r"\bremote youtube\b", r"\bremote animation\b", r"\bremote animator\b",
    r"\bremote cartoon\b", r"\bremote vfx\b", r"\bremote visual effects\b", r"\bremote 3d\b",
    r"\bremote 2d\b", r"\bremote motion graphics\b", r"\bremote technical artist\b",
    r"\bremote technical designer\b", r"\bremote web designer\b", r"\bremote video editor\b",
    r"\bremote video producer\b", r"\bremote content creator\b", r"\bremote content producer\b",
    r"\bremote youtube producer\b", r"\bremote youtube editor\b", r"\bremote animation artist\b",
    r"\bremote technical animator\b", r"\bremote virtual production\b", r"\bremote film\b",
    r"\bremote media\b", r"\bremote entertainment technology\b", r"\bwork[- ]from[- ]home\b",
    r"\bwork from home\b", r"\bdistributed team\b", r"\bdistributed engineering\b",
    r"\bdistributed development\b", r"\bdistributed workforce\b", r"\banywhere in the us\b",
    r"\bwork from anywhere\b",
]


NON_REMOTE_CONTEXT = [
    r"\bon[- ]site\b", r"\bonsite\b", r"\bin[- ]office\b", r"\boffice[- ]based\b",
    r"\bhybrid\b", r"\bhybrid[- ]remote\b", r"\bremote[- ]hybrid\b",
]


def _text(company: str, signal: str, evidence: str) -> str:
    return " ".join([company or "", signal or "", evidence or ""]).lower()


def _has_hiring_context(text: str) -> bool:
    return bool(re.search(HIRING_CONTEXT, text, re.IGNORECASE))


def _has_job_role_context(text: str) -> bool:
    return bool(re.search(JOB_ROLE_CONTEXT, text, re.IGNORECASE))


def _has_remote_context(text: str) -> bool:
    return any(bool(re.search(pattern, text, re.IGNORECASE)) for pattern in THORIO_REMOTE_RULES)


def _has_non_remote_context(text: str) -> bool:
    return any(bool(re.search(pattern, text, re.IGNORECASE)) for pattern in NON_REMOTE_CONTEXT)


def _matches(text: str, patterns: List[str]) -> int:
    return sum(bool(re.search(pattern, text, re.IGNORECASE)) for pattern in patterns)


def score_routes(company: str, signal: str, evidence: str) -> Dict[str, int]:
    text = _text(company, signal, evidence)
    scores = {"Shiftr": 0, "Paxus": 0, "Thorio": 0}

    if not (_has_hiring_context(text) or _has_job_role_context(text)):
        return scores

    scores["Shiftr"] = _matches(text, SHIFTR_RULES)
    scores["Paxus"] = _matches(text, PAXUS_RULES)

    # Thorio remains strictly remote. Hybrid/on-site roles are excluded.
    # Part-time remote roles are intentionally NOT excluded because
    # remote-only is the location requirement, not a full-time-only rule.
    if (
        _has_remote_context(text)
        and not _has_non_remote_context(text)
        and _has_job_role_context(text)
    ):
        scores["Thorio"] = 1

    return scores


def route(company: str, signal: str, evidence: str) -> str:
    scores = score_routes(company=company, signal=signal, evidence=evidence)

    if scores["Shiftr"] > 0:
        return "Shiftr"
    if scores["Paxus"] > 0:
        return "Paxus"
    if scores["Thorio"] > 0:
        return "Thorio"
    return "Review"


def potential_routes(company: str, signal: str, evidence: str) -> List[str]:
    scores = score_routes(company=company, signal=signal, evidence=evidence)
    return [name for name in ROUTES if scores[name] > 0]


if __name__ == "__main__":
    print(potential_routes("Acme", "remote software engineer", "Company is hiring a remote software engineer."))
