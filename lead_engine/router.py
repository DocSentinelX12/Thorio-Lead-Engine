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


# Specific technology, digital-media, creative-technology, and
# technical content roles. These establish meaningful job context.
#
# Generic company/technology terms are intentionally excluded.
# For example, "software company" must not become a Shiftr lead.
JOB_ROLE_CONTEXT = (
    # Software engineering and development
    r"\bsoftware engineer\b"
    r"|\bsoftware developer\b"
    r"|\bsoftware development engineer\b"
    r"|\bfull[- ]stack engineer\b"
    r"|\bfull[- ]stack developer\b"
    r"|\bfrontend engineer\b"
    r"|\bfront[- ]end engineer\b"
    r"|\bfrontend developer\b"
    r"|\bfront[- ]end developer\b"
    r"|\bbackend engineer\b"
    r"|\bback[- ]end engineer\b"
    r"|\bbackend developer\b"
    r"|\bback[- ]end developer\b"
    r"|\bweb developer\b"
    r"|\bweb engineer\b"
    r"|\bapplication developer\b"
    r"|\bapplication engineer\b"
    r"|\bmobile developer\b"
    r"|\bmobile engineer\b"
    r"|\bios developer\b"
    r"|\bios engineer\b"
    r"|\bandroid developer\b"
    r"|\bandroid engineer\b"
    r"|\bembedded software engineer\b"
    r"|\bembedded engineer\b"
    r"|\bfirmware engineer\b"
    r"|\bsystems engineer\b"
    r"|\bsoftware architect\b"
    r"|\bsoftware development\b"

    # Cloud, infrastructure, DevOps, SRE, and networking
    r"|\bdevops engineer\b"
    r"|\bdevops developer\b"
    r"|\bdevsecops engineer\b"
    r"|\bsite reliability engineer\b"
    r"|\bsre\b"
    r"|\bplatform engineer\b"
    r"|\bplatform developer\b"
    r"|\bcloud engineer\b"
    r"|\bcloud developer\b"
    r"|\bcloud architect\b"
    r"|\binfrastructure engineer\b"
    r"|\binfrastructure developer\b"
    r"|\bnetwork engineer\b"
    r"|\bnetwork administrator\b"
    r"|\bsystems administrator\b"
    r"|\bdatabase administrator\b"
    r"|\bdatabase engineer\b"
    r"|\bsolutions architect\b"
    r"|\bsolutions engineer\b"
    r"|\btechnical architect\b"
    r"|\bsite reliability\b"

    # Data, AI, machine learning, and analytics
    r"|\bdata engineer\b"
    r"|\bdata scientist\b"
    r"|\bdata analyst\b"
    r"|\bdata architect\b"
    r"|\bdata developer\b"
    r"|\bmachine learning engineer\b"
    r"|\bmachine learning developer\b"
    r"|\bmachine learning researcher\b"
    r"|\bml engineer\b"
    r"|\bmlops engineer\b"
    r"|\bmlops\b"
    r"|\bai engineer\b"
    r"|\bai developer\b"
    r"|\bartificial intelligence engineer\b"
    r"|\bartificial intelligence developer\b"
    r"|\bai researcher\b"
    r"|\bdeep learning engineer\b"
    r"|\bnlp engineer\b"
    r"|\bnatural language processing engineer\b"
    r"|\bcomputer vision engineer\b"
    r"|\bcomputer vision developer\b"
    r"|\bprompt engineer\b"
    r"|\bresearch engineer\b"
    r"|\bdata science\b"

    # Cybersecurity
    r"|\bcybersecurity engineer\b"
    r"|\bcyber security engineer\b"
    r"|\bsecurity engineer\b"
    r"|\binformation security engineer\b"
    r"|\bsecurity analyst\b"
    r"|\bsecurity architect\b"
    r"|\bsecurity researcher\b"
    r"|\bpenetration tester\b"
    r"|\bpenetration testing\b"
    r"|\bcloud security engineer\b"
    r"|\bapplication security engineer\b"
    r"|\bsecurity operations\b"
    r"|\bsoc analyst\b"

    # QA, testing, and automation
    r"|\bqa engineer\b"
    r"|\bquality assurance engineer\b"
    r"|\btest engineer\b"
    r"|\bsoftware tester\b"
    r"|\bautomation engineer\b"
    r"|\btest automation engineer\b"
    r"|\bquality engineer\b"
    r"|\bqa automation\b"

    # Product, UX, UI, web, and technical design
    r"|\bproduct manager\b"
    r"|\btechnical product manager\b"
    r"|\bproduct designer\b"
    r"|\bproduct design\b"
    r"|\bux designer\b"
    r"|\bux engineer\b"
    r"|\bui designer\b"
    r"|\bui engineer\b"
    r"|\bweb designer\b"
    r"|\bweb design\b"
    r"|\btechnical designer\b"
    r"|\binteraction designer\b"
    r"|\bexperience designer\b"
    r"|\bdigital designer\b"
    r"|\bdesign technologist\b"
    r"|\bcreative technologist\b"
    r"|\bvisual designer\b"
    r"|\bgraphic designer\b"
    r"|\bdigital product designer\b"

    # Developer relations and technical content
    r"|\bdeveloper advocate\b"
    r"|\bdeveloper advocacy\b"
    r"|\bdeveloper relations\b"
    r"|\bdevrel\b"
    r"|\btechnical evangelist\b"
    r"|\btechnical writer\b"
    r"|\btechnical writing\b"
    r"|\bdeveloper writer\b"
    r"|\btechnical content creator\b"
    r"|\btechnology content creator\b"
    r"|\btech content creator\b"
    r"|\bdeveloper content creator\b"
    r"|\btechnical content producer\b"
    r"|\btechnology content producer\b"
    r"|\btech content producer\b"
    r"|\btechnical content\b"
    r"|\btechnology content\b"
    r"|\bdeveloper content\b"

    # Video, media, and digital production
    r"|\bvideo editor\b"
    r"|\bvideo editing\b"
    r"|\bvideo producer\b"
    r"|\bvideo production\b"
    r"|\bdigital video producer\b"
    r"|\bdigital media producer\b"
    r"|\bcontent producer\b"
    r"|\bdigital content producer\b"
    r"|\bmedia producer\b"
    r"|\bmultimedia producer\b"
    r"|\bmultimedia designer\b"
    r"|\bmotion designer\b"
    r"|\bmotion graphics designer\b"
    r"|\bmotion graphics artist\b"
    r"|\bmotion graphics\b"
    r"|\bpost[- ]production editor\b"
    r"|\bpost[- ]production\b"
    r"|\bvideo production specialist\b"
    r"|\bdigital media specialist\b"

    # Animation, cartoon, 3D, VFX, and technical art
    r"|\btechnical artist\b"
    r"|\btechnical art\b"
    r"|\btechnical animator\b"
    r"|\b3d artist\b"
    r"|\b3d animator\b"
    r"|\b3d animation\b"
    r"|\b2d animator\b"
    r"|\b2d animation\b"
    r"|\bcharacter animator\b"
    r"|\bcharacter animation\b"
    r"|\banimation artist\b"
    r"|\banimation engineer\b"
    r"|\banimation developer\b"
    r"|\banimation technical director\b"
    r"|\btechnical director\b"
    r"|\brigging artist\b"
    r"|\brigger\b"
    r"|\bcharacter rigger\b"
    r"|\b3d modeler\b"
    r"|\b3d modeller\b"
    r"|\b3d modeling\b"
    r"|\b3d modelling\b"
    r"|\benvironment artist\b"
    r"|\bconcept artist\b"
    r"|\bvisual development artist\b"
    r"|\bvisual effects artist\b"
    r"|\bvfx artist\b"
    r"|\bvfx compositor\b"
    r"|\bcompositor\b"
    r"|\bvisual effects\b"
    r"|\bcomputer graphics\b"
    r"|\bcg artist\b"
    r"|\bcg generalist\b"
    r"|\blook development artist\b"
    r"|\blighting artist\b"
    r"|\bshader artist\b"
    r"|\brendering engineer\b"
    r"|\brendering developer\b"
    r"|\bgraphics engineer\b"
    r"|\bgraphics programmer\b"
    r"|\btechnical animation\b"
    r"|\bcartoon animator\b"
    r"|\bcartoon animation\b"
    r"|\bcharacter designer\b"
    r"|\bstoryboard artist\b"
    r"|\bstoryboard designer\b"

    # Film, television, streaming, and entertainment technology
    r"|\bvirtual production\b"
    r"|\bvirtual production artist\b"
    r"|\bvirtual production engineer\b"
    r"|\bvirtual production technician\b"
    r"|\bfilm technology\b"
    r"|\bfilm production technology\b"
    r"|\bdigital production\b"
    r"|\bdigital production artist\b"
    r"|\bpost[- ]production technology\b"
    r"|\bvideo technology\b"
    r"|\bmedia technology\b"
    r"|\bentertainment technology\b"
    r"|\bstreaming technology\b"
    r"|\bstreaming producer\b"
    r"|\bvirtual production technology\b"

    # YouTube, creator economy, and digital creator technology
    r"|\byoutube producer\b"
    r"|\byoutube editor\b"
    r"|\byoutube content creator\b"
    r"|\byoutube creator\b"
    r"|\byoutube video editor\b"
    r"|\byoutube production\b"
    r"|\bcreator producer\b"
    r"|\bcreator operations\b"
    r"|\bcreator technology\b"
    r"|\bcreator tools\b"
    r"|\bcreator economy\b"
    r"|\bcontent technology\b"
    r"|\bcontent operations\b"
    r"|\bcontent production\b"
    r"|\bdigital creator\b"
    r"|\bcontent creator\b"

    # IT and other technical roles
    r"|\btechnical support engineer\b"
    r"|\btechnical support specialist\b"
    r"|\btechnical support\b"
    r"|\bit support\b"
    r"|\bit specialist\b"
    r"|\bit engineer\b"
    r"|\binformation technology\b"
    r"|\btechnology consultant\b"
    r"|\btechnical consultant\b"
    r"|\btechnology professional\b"
    r"|\btechnical professional\b"
)


# Shiftr is the primary route for direct developer,
# engineering, software, technical contractor, and
# individual technical talent signals.
SHIFTR_RULES = [
    r"\bindividual developer\b",
    r"\bsoftware engineer\b",
    r"\bsoftware developer\b",
    r"\bsoftware development engineer\b",
    r"\bdeveloper\b",
    r"\bengineering hire\b",
    r"\bengineering hiring\b",
    r"\bcontract developer\b",
    r"\bcontract engineer\b",
    r"\bfreelance developer\b",
    r"\bindividual engineer\b",
    r"\bdeveloper contractor\b",
    r"\bsoftware development contractor\b",
    r"\btechnical contractor\b",
    r"\bengineering contractor\b",
    r"\bdevelopment team hiring\b",
    r"\bdevelopment contractor\b",
    r"\bsoftware contractor\b",
    r"\bengineering talent\b",
    r"\bdeveloper talent\b",
    r"\btechnical talent\b",
    r"\bengineering team\b",
    r"\bsoftware development team\b",
]


# Paxus is the recruitment/staffing route.
# These rules identify a need for recruiting,
# staffing, talent acquisition, or recruitment support
# for technology professionals.
PAXUS_RULES = [
    r"\btechnology recruitment\b",
    r"\btech recruitment\b",
    r"\bit recruitment\b",
    r"\btechnical recruitment\b",
    r"\btechnology staffing\b",
    r"\bit staffing\b",
    r"\btechnical staffing\b",
    r"\bengineering recruitment\b",
    r"\bengineering staffing\b",
    r"\btechnology talent acquisition\b",
    r"\bit talent acquisition\b",
    r"\brecruiting technology professionals\b",
    r"\bstaffing technology professionals\b",
    r"\brecruiting technical professionals\b",
    r"\bstaffing technical professionals\b",
    r"\brecruiting engineers\b",
    r"\bstaffing engineers\b",
    r"\brecruiting developers\b",
    r"\bstaffing developers\b",
    r"\btechnology recruiting\b",
    r"\btechnical recruiting\b",
    r"\bengineering recruiting\b",
    r"\btechnology hiring support\b",
    r"\btechnical hiring support\b",
    r"\bengineering hiring support\b",
    r"\brecruitment support\b",
    r"\bstaffing support\b",
    r"\btalent acquisition support\b",
    r"\brecruiting support\b",
]


# Thorio is explicitly REMOTE ONLY.
#
# These patterns identify remote/distributed/work-from-home
# technology or digital-content opportunities.
THORIO_REMOTE_RULES = [
    r"\bremote\b",
    r"\bremote[- ]first\b",
    r"\bfully remote\b",
    r"\b100% remote\b",
    r"\bremote only\b",
    r"\bremote position\b",
    r"\bremote role\b",
    r"\bremote job\b",
    r"\bremote opportunity\b",
    r"\bremote opening\b",
    r"\bremote hiring\b",
    r"\bremote engineer\b",
    r"\bremote developer\b",
    r"\bremote software\b",
    r"\bremote engineering\b",
    r"\bremote technology\b",
    r"\bremote tech\b",
    r"\bremote technical\b",
    r"\bremote data\b",
    r"\bremote ai\b",
    r"\bremote machine learning\b",
    r"\bremote product\b",
    r"\bremote design\b",
    r"\bremote designer\b",
    r"\bremote ux\b",
    r"\bremote ui\b",
    r"\bremote web\b",
    r"\bremote video\b",
    r"\bremote content\b",
    r"\bremote creator\b",
    r"\bremote youtube\b",
    r"\bremote animation\b",
    r"\bremote animator\b",
    r"\bremote cartoon\b",
    r"\bremote vfx\b",
    r"\bremote visual effects\b",
    r"\bremote 3d\b",
    r"\bremote 2d\b",
    r"\bremote motion graphics\b",
    r"\bremote technical artist\b",
    r"\bremote technical designer\b",
    r"\bremote web designer\b",
    r"\bremote video editor\b",
    r"\bremote video producer\b",
    r"\bremote content creator\b",
    r"\bremote content producer\b",
    r"\bremote youtube producer\b",
    r"\bremote youtube editor\b",
    r"\bremote animator\b",
    r"\bremote animation artist\b",
    r"\bremote technical animator\b",
    r"\bremote virtual production\b",
    r"\bremote film\b",
    r"\bremote media\b",
    r"\bremote entertainment technology\b",
    r"\bwork[- ]from[- ]home\b",
    r"\bwork from home\b",
    r"\bdistributed team\b",
    r"\bdistributed engineering\b",
    r"\bdistributed development\b",
    r"\bdistributed workforce\b",
    r"\banywhere in the us\b",
    r"\bwork from anywhere\b",
]


# Explicit non-remote language prevents a conflicting source
# from being treated as a Thorio remote opportunity.
NON_REMOTE_CONTEXT = [
    r"\bon[- ]site\b",
    r"\bonsite\b",
    r"\bin[- ]office\b",
    r"\boffice[- ]based\b",
    r"\bhybrid\b",
    r"\bhybrid[- ]remote\b",
    r"\bpart[- ]time remote\b",
    r"\bremote[- ]hybrid\b",
]


def _text(
    company: str,
    signal: str,
    evidence: str,
) -> str:
    return " ".join(
        [
            company or "",
            signal or "",
            evidence or "",
        ]
    ).lower()


def _has_hiring_context(
    text: str,
) -> bool:
    return bool(
        re.search(
            HIRING_CONTEXT,
            text,
            re.IGNORECASE,
        )
    )


def _has_job_role_context(
    text: str,
) -> bool:
    return bool(
        re.search(
            JOB_ROLE_CONTEXT,
            text,
            re.IGNORECASE,
        )
    )


def _has_remote_context(
    text: str,
) -> bool:
    return any(
        bool(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )
        for pattern in THORIO_REMOTE_RULES
    )


def _has_non_remote_context(
    text: str,
) -> bool:
    return any(
        bool(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )
        for pattern in NON_REMOTE_CONTEXT
    )


def _matches(
    text: str,
    patterns: List[str],
) -> int:
    return sum(
        bool(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
        )
        for pattern in patterns
    )


def score_routes(
    company: str,
    signal: str,
    evidence: str,
) -> Dict[str, int]:
    """
    Score an opportunity for each business route.

    Routing identifies business relevance only.
    Qualification is handled elsewhere in the pipeline.

    A lead may be relevant to more than one destination.

    Shiftr:
        Direct developer, software, engineering, and
        technical contractor/talent signals.

    Paxus:
        Recruitment, staffing, talent acquisition, and
        technical hiring-support signals.

    Thorio:
        REMOTE technology and digital-content opportunities only.
    """

    text = _text(
        company,
        signal,
        evidence,
    )

    scores = {
        "Shiftr": 0,
        "Paxus": 0,
        "Thorio": 0,
    }

    if not (
        _has_hiring_context(text)
        or _has_job_role_context(text)
    ):
        return scores

    scores["Shiftr"] = _matches(
        text,
        SHIFTR_RULES,
    )

    scores["Paxus"] = _matches(
        text,
        PAXUS_RULES,
    )

    if (
        _has_remote_context(text)
        and not _has_non_remote_context(text)
        and _has_job_role_context(text)
    ):
        scores["Thorio"] = 1

    return scores


def route(
    company: str,
    signal: str,
    evidence: str,
) -> str:
    """
    Return the primary business route.

    Direct developer/software/engineering signals
    default to Shiftr.

    Recruitment/staffing signals default to Paxus.

    Remote technology/content opportunities default
    to Thorio when no stronger Shiftr or Paxus signal exists.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    if scores["Shiftr"] > 0:
        return "Shiftr"

    if scores["Paxus"] > 0:
        return "Paxus"

    if scores["Thorio"] > 0:
        return "Thorio"

    return "Review"


def potential_routes(
    company: str,
    signal: str,
    evidence: str,
) -> List[str]:
    """
    Return every business route with a positive score.
    """

    scores = score_routes(
        company=company,
        signal=signal,
        evidence=evidence,
    )

    return [
        name
        for name in ROUTES
        if scores[name] > 0
    ]


if __name__ == "__main__":
    print(
        potential_routes(
            "Acme",
            "remote software engineer",
            "Company is hiring a remote software engineer.",
        )
)
