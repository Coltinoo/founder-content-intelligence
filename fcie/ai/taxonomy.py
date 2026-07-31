"""Theme taxonomy and entity dictionary.

Shared by the LLM analyser (as the allowed label set, which keeps clustering
stable across runs) and the heuristic analyser (as the matching rules).

Each theme carries the keyword/phrase evidence that assigns a source to it.
Themes are matched against the *source text*, so assignment is always traceable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class ThemeDef:
    slug: str
    name: str
    description: str
    keywords: tuple[str, ...]
    strong_keywords: tuple[str, ...] = ()   # worth double weight
    industries: tuple[str, ...] = ()
    # Context that means a keyword hit is a false positive. "After-hours" is a
    # local-business staffing term *and* a stock-market term; without this,
    # "after-hours trading" gets filed under missed customer calls.
    negative_keywords: tuple[str, ...] = ()


THEMES: tuple[ThemeDef, ...] = (
    ThemeDef(
        slug="missed-after-hours-leads",
        name="Missed after-hours leads",
        description="Demand arriving outside staffed hours that never gets answered.",
        keywords=("after hours", "after-hours", "nights and weekends", "voicemail",
                  "unanswered call", "missed call", "out of office", "24/7", "off hours"),
        strong_keywords=("missed call", "after-hours", "unanswered call"),
        negative_keywords=("after-hours trading", "after hours trading", "premarket",
                           "share price", "stock rose", "stock up", "shareholder",
                           "earnings call", "wall street"),
    ),
    ThemeDef(
        slug="speed-to-lead",
        name="Speed to lead",
        description="How fast a business responds to an inbound enquiry, and what slow response costs.",
        keywords=("speed to lead", "response time", "respond within", "first response",
                  "minutes to respond", "lead response", "instant reply", "reply time"),
        strong_keywords=("speed to lead", "lead response", "response time"),
    ),
    ThemeDef(
        slug="customer-follow-up-failure",
        name="Customer follow-up failures",
        description="Leads and existing customers who are never followed up with after first contact.",
        keywords=("follow up", "follow-up", "nurture", "no follow through", "dropped lead",
                  "never called back", "cadence", "drip", "reengage"),
        strong_keywords=("follow-up", "follow up"),
    ),
    ThemeDef(
        slug="human-ai-handoff",
        name="Human-to-AI handoffs",
        description="When and how an AI agent hands a conversation to a person, and vice versa.",
        keywords=("handoff", "hand off", "escalate", "escalation", "human in the loop",
                  "transfer to a human", "human agent", "human review"),
        strong_keywords=("handoff", "human in the loop", "escalation"),
    ),
    ThemeDef(
        slug="ai-implementation-challenges",
        name="AI implementation challenges",
        description="The practical difficulty of deploying AI: integration, data, training, change management.",
        keywords=("implementation", "deployment", "rollout", "integration", "onboarding",
                  "change management", "pilot", "proof of concept", "adoption barrier",
                  "training data", "roi of ai", "failed pilot"),
        strong_keywords=("implementation", "adoption", "rollout"),
    ),
    ThemeDef(
        slug="ai-employee-accountability",
        name="AI employee accountability",
        description="Holding an AI agent to a job description, quota, or measurable outcome.",
        keywords=("ai employee", "digital worker", "ai worker", "accountable", "quota",
                  "job description", "performance", "kpi", "owns the outcome", "ai teammate"),
        strong_keywords=("ai employee", "digital worker", "ai teammate"),
    ),
    ThemeDef(
        slug="revenue-owning-agents",
        name="Revenue ownership by AI",
        description="AI measured on booked jobs, appointments and revenue rather than deflected tickets.",
        keywords=("revenue", "booked", "appointment", "close rate", "conversion",
                  "pipeline", "upsell", "sales agent", "revenue per", "bookings"),
        strong_keywords=("revenue", "booked appointment", "conversion"),
        # Big-tech quarterly results are not evidence about local-business agents.
        negative_keywords=("year over year", "for the quarter", "guidance",
                           "share price", "shareholder", "earnings call",
                           "wall street", "market cap", "cloud revenue"),
    ),
    ThemeDef(
        slug="local-business-staffing",
        name="Local-business staffing limits",
        description="Small teams, front-desk turnover, and labour shortage constraining responsiveness.",
        keywords=("staffing", "labor shortage", "labour shortage", "hiring", "turnover",
                  "front desk", "receptionist", "short staffed", "understaffed",
                  "headcount", "technician shortage", "skilled trades"),
        strong_keywords=("labor shortage", "short staffed", "front desk", "receptionist"),
    ),
    ThemeDef(
        slug="ai-skepticism",
        name="AI skepticism and trust",
        description="Buyer doubt, hype fatigue, and trust barriers around AI claims.",
        keywords=("skeptic", "sceptic", "hype", "overhyped", "distrust", "trust",
                  "backlash", "disappointing", "underwhelming", "ai washing", "bubble"),
        strong_keywords=("hype", "skeptic", "ai washing"),
    ),
    ThemeDef(
        slug="vertical-specific-ai",
        name="Vertical-specific AI knowledge",
        description="AI that knows an industry's vocabulary, pricing and workflow versus generic assistants.",
        keywords=("vertical", "industry-specific", "domain knowledge", "purpose-built",
                  "trained on", "specialized", "specialised", "niche", "vertical saas"),
        strong_keywords=("vertical", "industry-specific", "purpose-built"),
    ),
    ThemeDef(
        slug="customer-reactivation",
        name="Customer reactivation",
        description="Winning back dormant customers from an existing database.",
        keywords=("reactivation", "win back", "winback", "dormant", "lapsed",
                  "database", "past customers", "repeat business", "retention",
                  "customer list", "reengagement"),
        strong_keywords=("reactivation", "win back", "lapsed customer"),
    ),
    ThemeDef(
        slug="ai-source-transparency",
        name="AI source transparency",
        description="Showing where an AI answer came from; citations, auditability and hallucination control.",
        keywords=("hallucination", "citation", "transparency", "explainab", "audit trail",
                  "source of truth", "grounded", "provenance", "verify", "accuracy"),
        strong_keywords=("hallucination", "citation", "grounded", "provenance"),
    ),
    ThemeDef(
        slug="ai-replaces-workflows",
        name="AI replacing workflows, not jobs",
        description="Framing AI as absorbing tasks and workflows rather than eliminating roles.",
        keywords=("replace jobs", "job displacement", "augment", "free up staff",
                  "workflow", "busywork", "repetitive tasks", "automation of tasks",
                  "not replacing", "headcount reduction"),
        strong_keywords=("augment", "busywork", "job displacement"),
    ),
    ThemeDef(
        slug="agents-vs-chatbots",
        name="Agents that act vs chatbots that answer",
        description="The gap between conversational bots and agents that complete a transaction.",
        keywords=("chatbot", "agentic", "ai agent", "takes action", "completes",
                  "end to end", "autonomous", "orchestration", "tool use", "workflow automation"),
        strong_keywords=("agentic", "ai agent", "chatbot", "autonomous"),
        # "Autonomous" is also robotics and self-driving vocabulary. A robot
        # vacuum is not a software agent that books a job.
        negative_keywords=("robot vacuum", "self-driving", "autonomous vehicle",
                           "lidar", "drone", "roomba", "warehouse robot"),
    ),
    ThemeDef(
        slug="local-business-ai-adoption",
        name="Local-business AI adoption",
        description="How small and local businesses actually buy, trial and adopt AI tools.",
        keywords=("small business", "local business", "smb", "main street", "mom and pop",
                  "independent business", "franchise", "multi-location"),
        strong_keywords=("small business", "local business", "smb"),
    ),
    ThemeDef(
        slug="review-and-reputation",
        name="Reviews and online reputation",
        description="Review volume, response and reputation as a local-demand driver.",
        keywords=("review", "reputation", "google business profile", "star rating",
                  "testimonial", "yelp", "ratings", "review response"),
        strong_keywords=("reputation", "google business profile", "star rating"),
    ),
    ThemeDef(
        slug="messaging-as-primary-channel",
        name="Messaging as the primary customer channel",
        description="Text and messaging displacing phone and email for local commerce.",
        keywords=("text message", "sms", "messaging", "texting", "webchat", "chat widget",
                  "whatsapp", "conversational", "two-way messaging"),
        strong_keywords=("sms", "texting", "webchat", "two-way messaging"),
    ),
    ThemeDef(
        slug="ai-cost-and-roi",
        name="AI cost and measurable ROI",
        description="Pricing models, payback periods and provable return on AI spend.",
        keywords=("roi", "return on investment", "payback", "cost per", "pricing",
                  "budget", "cost savings", "outcome-based pricing", "per seat"),
        strong_keywords=("roi", "payback", "outcome-based pricing"),
    ),
)

THEME_BY_SLUG = {t.slug: t for t in THEMES}
THEME_NAMES = [t.name for t in THEMES]


# ── entity dictionary ───────────────────────────────────────────────────────

PODIUM_ENTITIES = {
    "podium": "Podium",
    "eric rea": "Eric Rea",
    "dennis steele": "Dennis Steele",
    "ai employee": "Podium AI Employee",
}

COMPETITOR_ENTITIES = {
    "birdeye": "Birdeye",
    "thryv": "Thryv",
    "weave": "Weave",
    "servicetitan": "ServiceTitan",
    "housecall pro": "Housecall Pro",
    "jobber": "Jobber",
    "hubspot": "HubSpot",
    "salesforce": "Salesforce",
    "zendesk": "Zendesk",
    "intercom": "Intercom",
    "sierra ai": "Sierra AI",
    "decagon": "Decagon",
    "cdk global": "CDK Global",
    "dealersocket": "DealerSocket",
    "tekion": "Tekion",
    "boulevard": "Boulevard",
    "mindbody": "Mindbody",
    "vagaro": "Vagaro",
    "podium ai": "Podium",
    "yelp": "Yelp",
    "angi": "Angi",
    "thumbtack": "Thumbtack",
}

AI_VENDOR_ENTITIES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "microsoft": "Microsoft",
    "nvidia": "Nvidia",
    "meta": "Meta",
    "amazon": "Amazon",
}

INDUSTRY_KEYWORDS = {
    "Automotive": ("dealership", "dealer", "automotive", "auto retail", "car buyer",
                   "service department", "vehicle", "franchise dealer", "used car"),
    "Home services": ("hvac", "plumbing", "plumber", "electrician", "roofing", "landscaping",
                      "home services", "contractor", "pest control", "garage door", "trades"),
    "Aesthetics & medspa": ("medspa", "med spa", "aesthetic", "dermatology", "botox",
                            "injectables", "spa", "cosmetic", "wellness clinic"),
    "Healthcare": ("dental", "dentist", "clinic", "patient", "healthcare", "optometry",
                   "veterinary", "chiropract"),
    "Retail": ("retail", "storefront", "furniture store", "jewelry", "boutique", "showroom"),
    "B2B SaaS": ("saas", "b2b software", "arr", "churn", "seat-based", "enterprise software",
                 "go-to-market", "product-led"),
    "Professional services": ("law firm", "accounting", "insurance agency", "real estate",
                              "mortgage", "financial advisor"),
}

CUSTOMER_SEGMENTS = {
    "Local SMB (single location)": ("small business", "single location", "owner-operator",
                                    "mom and pop", "independent"),
    # "chain" and "group" alone are too generic ("supply chain", "a group of
    # researchers"), so the phrases here stay specific enough to mean something.
    "Multi-location / franchise": ("multi-location", "franchise", "locations across",
                                   "rooftops", "store chain", "dealer group",
                                   "multiple locations"),
    "Mid-market": ("mid-market", "midmarket", "growing company", "scale-up"),
    "Enterprise": ("enterprise", "fortune 500", "global organization", "large organisation"),
}

# Language that marks vendor marketing rather than reporting.
PROMOTIONAL_DOMAINS = {"podium.com"}


@lru_cache(maxsize=4096)
def _phrase_pattern(phrase: str, allow_plural: bool = True) -> re.Pattern[str]:
    r"""Word-boundary matcher for a keyword or multi-word phrase.

    Plain substring matching is badly wrong here: ``"spa"`` matches *space*,
    *spark* and *disparate*, which was enough to make "Aesthetics & medspa" the
    top-ranked industry across a corpus containing two beauty sources. Likewise
    ``"lead"`` matches *leader* and *misleading*, corrupting theme assignment.

    ``allow_plural`` adds an optional trailing ``s`` so one keyword covers its
    plural. It is disabled for organisation names, which do not pluralise —
    "podiums" is a piece of furniture, not the company.
    """
    escaped = re.escape(phrase.strip()).replace(r"\ ", r"\s+")
    suffix = "s?" if allow_plural else ""
    return re.compile(rf"(?<!\w){escaped}{suffix}(?!\w)", re.IGNORECASE)


def count_phrase(text: str, phrase: str, *, allow_plural: bool = True) -> int:
    """Occurrences of ``phrase`` in ``text`` respecting word boundaries."""
    if not text or not phrase:
        return 0
    return len(_phrase_pattern(phrase, allow_plural).findall(text))


def contains_phrase(text: str, phrase: str, *, allow_plural: bool = True) -> bool:
    if not text or not phrase:
        return False
    return _phrase_pattern(phrase, allow_plural).search(text) is not None


def match_themes(text: str, top_n: int = 4) -> list[tuple[ThemeDef, float, list[str]]]:
    """Score every theme against ``text``.

    Returns ``[(theme, score, matched_keywords)]`` sorted best-first. Scores are
    raw keyword-evidence counts — the caller decides thresholds. Matching is
    literal so a theme assignment can always be justified from the source.
    """
    if not text:
        return []
    results: list[tuple[ThemeDef, float, list[str]]] = []
    for theme in THEMES:
        matched: list[str] = []
        score = 0.0
        for kw in theme.keywords:
            count = count_phrase(text, kw)
            if count:
                matched.append(kw)
                score += min(count, 4) * 1.0
        for kw in theme.strong_keywords:
            count = count_phrase(text, kw)
            if count:
                score += min(count, 4) * 1.5
        # Context that marks the hits as a different sense of the same words.
        negatives = sum(count_phrase(text, kw) for kw in theme.negative_keywords)
        if negatives:
            score -= negatives * 3.0
        if score > 0:
            results.append((theme, score, matched))
    results.sort(key=lambda row: row[1], reverse=True)
    return results[:top_n]


def match_entities(text: str) -> dict[str, list[str]]:
    """Find known organisations and people mentioned in the text."""
    found = {"podium": [], "competitors": [], "ai_vendors": []}
    if not text:
        return found
    # Organisation names are matched without plural tolerance — "podiums" is
    # furniture, not the company.
    for key, label in PODIUM_ENTITIES.items():
        if contains_phrase(text, key, allow_plural=False) and label not in found["podium"]:
            found["podium"].append(label)
    for key, label in COMPETITOR_ENTITIES.items():
        if (contains_phrase(text, key, allow_plural=False)
                and label not in found["competitors"] and label != "Podium"):
            found["competitors"].append(label)
    for key, label in AI_VENDOR_ENTITIES.items():
        if contains_phrase(text, key, allow_plural=False) and label not in found["ai_vendors"]:
            found["ai_vendors"].append(label)
    return found


# An industry needs more than one passing mention before it is attributed.
INDUSTRY_MIN_HITS = 2


def match_industries(text: str) -> list[str]:
    """Industries actually discussed, not merely name-checked once."""
    if not text:
        return ["Cross-industry"]
    hits: list[tuple[str, int]] = []
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        count = sum(count_phrase(text, k) for k in keywords)
        if count >= INDUSTRY_MIN_HITS:
            hits.append((industry, count))
    hits.sort(key=lambda row: (-row[1], row[0]))
    return [industry for industry, _ in hits[:3]] or ["Cross-industry"]


def match_customer_segment(text: str) -> str:
    if not text:
        return "Not specified in source"
    best, best_count = "Not specified in source", 0
    for segment, keywords in CUSTOMER_SEGMENTS.items():
        count = sum(count_phrase(text, k) for k in keywords)
        if count > best_count:
            best, best_count = segment, count
    return best
