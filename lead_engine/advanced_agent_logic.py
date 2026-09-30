"""Stateless professional logic for high-volume discovery and social research.

Discovery produces observed evidence only. Research produces researched evidence
with provenance. Revenue-stage actions consume completed verified research and
are delegated to the high-ticket sales closer boundary.
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from .outreach_engine import OutreachContractError, apply_outcome, build_outreach_decision, objection_response
from .agent_queue import enqueue, enqueue_many
from .active_processing import airtable_integrity, priority, routing, verification
from .public_research import research_public_web

DISCOVERY_TARGETS = {
    "engineering_demand_discovery": ("software", "engineer", "developer", "backend", "frontend", "full stack", "devops", "platform", "engineering"),
    "ai_demand_discovery": ("ai", "artificial intelligence", "machine learning", "ml", "llm", "agent", "automation", "data scientist", "data engineering"),
    "product_design_demand_discovery": ("product manager", "product", "ux", "ui", "design", "designer", "user experience"),
    "contract_team_demand_discovery": ("contract", "contractor", "staff augmentation", "outsourc", "dedicated team", "development team", "agency", "freelance"),
    "astrivon_demand_discovery": (
        "dev agency", "tech partner", "mvp", "b2b outreach", "b2b sales",
        "lead generation", "sales automation", "ai/ml", "computer vision",
    ),
}

