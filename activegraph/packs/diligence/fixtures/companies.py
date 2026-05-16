"""Three companies' worth of recorded diligence fixtures.

CONTRACT v0.9 #18: fixtures ship with the pack. Three companies. Each
gets:
  - a set of documents (returned by fetch_company_docs)
  - per-URL summaries (returned by summarize_document)
  - a question list (returned by question_generator)
  - per-(company, question) research findings with claims
  - a risk list
  - a final memo body

The three companies are fictional. They are designed to exercise the
pack: company B has a contradiction (two researchers report opposing
revenue trajectories from different sources), company A is clean, and
company C has a high-severity risk.
"""

from __future__ import annotations


THREE_COMPANIES = [
    {
        "name": "Northwind Robotics",
        "ticker": "NWR",
        "sector": "Industrial Automation",
        "description": "Builds collaborative robots for SMB manufacturers.",
    },
    {
        "name": "Stellar Logistics",
        "ticker": "STLG",
        "sector": "Supply Chain",
        "description": "Last-mile delivery network across the US Northeast.",
    },
    {
        "name": "Pinecone Bio",
        "ticker": "PCB",
        "sector": "Therapeutics",
        "description": "Pre-clinical-stage biotech developing oncology assets.",
    },
]


def company_goal(company: dict) -> str:
    return f"Diligence: {company['name']}"


# ---------------------------------------------------- documents per company

DOCS_BY_COMPANY = {
    "northwind robotics": [
        {
            "title": "Q3 Operating Update",
            "url": "https://fixtures.activegraph.local/northwind/q3-update",
            "summary": "Q3 revenue up 28% YoY; gross margin steady at 41%.",
        },
        {
            "title": "Customer Concentration Disclosure",
            "url": "https://fixtures.activegraph.local/northwind/customer-concentration",
            "summary": "Top three customers represent 52% of annual revenue.",
        },
        {
            "title": "Product Roadmap Brief",
            "url": "https://fixtures.activegraph.local/northwind/roadmap",
            "summary": "New cobot SKU launching Q1; targets food-and-beverage segment.",
        },
    ],
    "stellar logistics": [
        {
            "title": "Annual Report Excerpts",
            "url": "https://fixtures.activegraph.local/stellar/annual",
            "summary": "Network expanded to 14 metros; revenue +18% YoY.",
        },
        {
            "title": "Carrier Survey",
            "url": "https://fixtures.activegraph.local/stellar/carrier-survey",
            "summary": "Independent driver survey suggests revenue per route declined in Q3 — divergent from filing.",
        },
        {
            "title": "Investor Day Transcript",
            "url": "https://fixtures.activegraph.local/stellar/investor-day",
            "summary": "Management reiterates 20% YoY growth target through next year.",
        },
    ],
    "pinecone bio": [
        {
            "title": "Pre-clinical Program Update",
            "url": "https://fixtures.activegraph.local/pinecone/preclinical",
            "summary": "PCB-101 advances toward IND filing; PCB-202 deprioritized.",
        },
        {
            "title": "FDA Pre-IND Correspondence",
            "url": "https://fixtures.activegraph.local/pinecone/fda-meeting",
            "summary": "FDA flagged manufacturing controls; resolution required before IND.",
        },
        {
            "title": "Cash Runway Note",
            "url": "https://fixtures.activegraph.local/pinecone/runway",
            "summary": "Cash runway estimated through Q2 next year at current burn.",
        },
    ],
}


FILINGS_BY_COMPANY = {
    name: [{"title": d["title"], "url": d["url"], "summary": d["summary"]} for d in docs]
    for name, docs in DOCS_BY_COMPANY.items()
}


# ---------------------------------------------------- URL → summary + facts

SUMMARIES_BY_URL = {
    "https://fixtures.activegraph.local/northwind/q3-update": {
        "summary": "Northwind Robotics reported Q3 revenue of $42M, up 28% YoY. Gross margin held at 41%. Operating loss narrowed to $3M.",
        "facts": [
            "Q3 revenue: $42M, +28% YoY",
            "Gross margin: 41%",
            "Operating loss: $3M",
        ],
    },
    "https://fixtures.activegraph.local/northwind/customer-concentration": {
        "summary": "Top three customers represent 52% of annual revenue; the largest single customer is 26%.",
        "facts": [
            "Top 3 customers: 52% of revenue",
            "Largest customer: 26%",
        ],
    },
    "https://fixtures.activegraph.local/northwind/roadmap": {
        "summary": "New cobot SKU 'NW-7' launches Q1 next year, targeting food-and-beverage SMB operators.",
        "facts": [
            "NW-7 cobot launches Q1",
            "Targets food-and-beverage SMB",
        ],
    },
    "https://fixtures.activegraph.local/stellar/annual": {
        "summary": "Stellar Logistics reports 18% YoY revenue growth, expanded to 14 metros, with positive unit economics in 9 of 14.",
        "facts": [
            "Revenue +18% YoY",
            "14 metros covered",
            "Positive unit economics in 9 of 14",
        ],
    },
    "https://fixtures.activegraph.local/stellar/carrier-survey": {
        "summary": "Independent survey of 200 drivers suggests revenue per route declined in Q3, contradicting filings.",
        "facts": [
            "Driver-reported revenue per route: -7% Q3",
            "200 driver responses",
            "Diverges from filed +18% growth claim",
        ],
    },
    "https://fixtures.activegraph.local/stellar/investor-day": {
        "summary": "Management reiterates 20% YoY growth target through next year and announces 4 new metro launches.",
        "facts": [
            "Management 20% growth target",
            "4 new metro launches planned",
        ],
    },
    "https://fixtures.activegraph.local/pinecone/preclinical": {
        "summary": "PCB-101 advances toward IND filing in H2; PCB-202 program deprioritized to focus resources.",
        "facts": [
            "PCB-101 IND target H2",
            "PCB-202 deprioritized",
        ],
    },
    "https://fixtures.activegraph.local/pinecone/fda-meeting": {
        "summary": "FDA pre-IND correspondence flagged manufacturing controls as requiring resolution before IND.",
        "facts": [
            "FDA flagged manufacturing controls",
            "Resolution required pre-IND",
        ],
    },
    "https://fixtures.activegraph.local/pinecone/runway": {
        "summary": "Cash runway estimated through Q2 next year at current burn; raise likely required.",
        "facts": [
            "Runway: through Q2 next year",
            "Raise likely required",
        ],
    },
}


# ---------------------------------------------------- questions per company

QUESTIONS_BY_COMPANY = {
    "northwind robotics": [
        "What is the company's Q3 revenue trajectory?",
        "How concentrated is the customer base?",
        "What is the gross margin profile?",
        "What new products are launching in the next twelve months?",
        "What is the operating cash burn?",
        "Who are the main competitors?",
        "What is the addressable market for cobots in SMB manufacturing?",
        "What regulatory exposures exist?",
    ],
    "stellar logistics": [
        "What is the revenue growth rate?",
        "How many metros does the network cover?",
        "What is the unit economics picture per metro?",
        "Is there any divergence between filed numbers and independent data?",
        "What is the carrier (driver) retention rate?",
        "What is management's growth guidance?",
        "Who are the main competitors?",
        "What is the regulatory exposure?",
    ],
    "pinecone bio": [
        "What is the lead program's regulatory status?",
        "What is the cash runway?",
        "What did the FDA pre-IND meeting reveal?",
        "What are the secondary programs?",
        "What is the burn rate?",
        "Who is on the leadership team?",
        "What is the competitive landscape for the lead asset?",
        "What is the manufacturing strategy?",
    ],
}


# ---------------------------------------------------- per-question findings
#
# Keyed by (company_name_lower, question_text). When a question doesn't
# appear here, the recorded provider returns a generic low-confidence
# placeholder.

RESEARCH_FINDINGS_BY_QUESTION = {
    ("northwind robotics", "What is the company's Q3 revenue trajectory?"): {
        "document_url": "https://fixtures.activegraph.local/northwind/q3-update",
        "summary": "Q3 revenue +28% YoY at $42M.",
        "claims": [
            {
                "text": "Northwind Q3 revenue grew 28% YoY to $42M.",
                "confidence": 0.92,
                "source_document_url": "https://fixtures.activegraph.local/northwind/q3-update",
                "evidence_quote": "Q3 revenue: $42M, +28% YoY",
            },
        ],
    },
    ("northwind robotics", "How concentrated is the customer base?"): {
        "document_url": "https://fixtures.activegraph.local/northwind/customer-concentration",
        "summary": "Top three customers = 52% of revenue; largest single = 26%.",
        "claims": [
            {
                "text": "Northwind's top three customers represent 52% of annual revenue.",
                "confidence": 0.95,
                "source_document_url": "https://fixtures.activegraph.local/northwind/customer-concentration",
                "evidence_quote": "Top 3 customers: 52% of revenue",
            },
            {
                "text": "Northwind's single largest customer represents 26% of revenue.",
                "confidence": 0.95,
                "source_document_url": "https://fixtures.activegraph.local/northwind/customer-concentration",
                "evidence_quote": "Largest customer: 26%",
            },
        ],
    },
    ("northwind robotics", "What is the gross margin profile?"): {
        "document_url": "https://fixtures.activegraph.local/northwind/q3-update",
        "summary": "Gross margin held at 41% in Q3.",
        "claims": [
            {
                "text": "Northwind's Q3 gross margin was 41%, flat sequentially.",
                "confidence": 0.9,
                "source_document_url": "https://fixtures.activegraph.local/northwind/q3-update",
                "evidence_quote": "Gross margin: 41%",
            },
        ],
    },
    ("northwind robotics", "What new products are launching in the next twelve months?"): {
        "document_url": "https://fixtures.activegraph.local/northwind/roadmap",
        "summary": "New cobot SKU NW-7 launches Q1, targets F&B SMB.",
        "claims": [
            {
                "text": "Northwind plans to launch the NW-7 cobot in Q1, targeting food-and-beverage SMB.",
                "confidence": 0.85,
                "source_document_url": "https://fixtures.activegraph.local/northwind/roadmap",
                "evidence_quote": "NW-7 cobot launches Q1",
            },
        ],
    },
    ("stellar logistics", "What is the revenue growth rate?"): {
        "document_url": "https://fixtures.activegraph.local/stellar/annual",
        "summary": "Stellar reports 18% YoY revenue growth in annual filings.",
        "claims": [
            {
                "text": "Stellar Logistics revenue grew 18% YoY per the annual filing.",
                "confidence": 0.9,
                "source_document_url": "https://fixtures.activegraph.local/stellar/annual",
                "evidence_quote": "Revenue +18% YoY",
            },
        ],
    },
    ("stellar logistics", "Is there any divergence between filed numbers and independent data?"): {
        "document_url": "https://fixtures.activegraph.local/stellar/carrier-survey",
        "summary": "Carrier survey suggests revenue per route declined Q3, diverging from filings.",
        "claims": [
            {
                "text": "Independent carrier survey suggests Stellar revenue per route declined 7% in Q3.",
                "confidence": 0.78,
                "source_document_url": "https://fixtures.activegraph.local/stellar/carrier-survey",
                "evidence_quote": "Driver-reported revenue per route: -7% Q3",
                # This contradicts the +18% claim above.
                "contradicts_claim_text": "Stellar Logistics revenue grew 18% YoY per the annual filing.",
            },
        ],
    },
    ("stellar logistics", "How many metros does the network cover?"): {
        "document_url": "https://fixtures.activegraph.local/stellar/annual",
        "summary": "Network covers 14 metros as of latest annual.",
        "claims": [
            {
                "text": "Stellar's network covers 14 metros, with positive unit economics in 9 of them.",
                "confidence": 0.88,
                "source_document_url": "https://fixtures.activegraph.local/stellar/annual",
                "evidence_quote": "14 metros covered",
            },
        ],
    },
    ("stellar logistics", "What is management's growth guidance?"): {
        "document_url": "https://fixtures.activegraph.local/stellar/investor-day",
        "summary": "Investor Day: 20% growth target through next year.",
        "claims": [
            {
                "text": "Management guides for 20% YoY revenue growth through next year.",
                "confidence": 0.8,
                "source_document_url": "https://fixtures.activegraph.local/stellar/investor-day",
                "evidence_quote": "Management 20% growth target",
            },
        ],
    },
    ("pinecone bio", "What is the lead program's regulatory status?"): {
        "document_url": "https://fixtures.activegraph.local/pinecone/preclinical",
        "summary": "PCB-101 targets IND filing in H2.",
        "claims": [
            {
                "text": "PCB-101 is targeted for IND filing in H2 of next year.",
                "confidence": 0.82,
                "source_document_url": "https://fixtures.activegraph.local/pinecone/preclinical",
                "evidence_quote": "PCB-101 IND target H2",
            },
        ],
    },
    ("pinecone bio", "What did the FDA pre-IND meeting reveal?"): {
        "document_url": "https://fixtures.activegraph.local/pinecone/fda-meeting",
        "summary": "FDA flagged manufacturing controls requiring resolution pre-IND.",
        "claims": [
            {
                "text": "FDA pre-IND correspondence flagged Pinecone's manufacturing controls as requiring resolution before IND filing.",
                "confidence": 0.9,
                "source_document_url": "https://fixtures.activegraph.local/pinecone/fda-meeting",
                "evidence_quote": "FDA flagged manufacturing controls",
            },
        ],
    },
    ("pinecone bio", "What is the cash runway?"): {
        "document_url": "https://fixtures.activegraph.local/pinecone/runway",
        "summary": "Runway through Q2 at current burn; raise likely needed.",
        "claims": [
            {
                "text": "Pinecone Bio's cash runway extends through Q2 of next year at current burn; a financing round is likely required to reach IND filing.",
                "confidence": 0.85,
                "source_document_url": "https://fixtures.activegraph.local/pinecone/runway",
                "evidence_quote": "Runway: through Q2 next year",
            },
        ],
    },
}


# ---------------------------------------------------- risks per company

RISKS_BY_COMPANY = {
    "northwind robotics": [
        {
            "title": "customer concentration",
            "description": (
                "Top three customers represent over half of annual revenue; loss of "
                "the largest customer (26%) would materially impair financials."
            ),
            "severity": "high",
            "related_claim_texts": [
                "Northwind's top three customers represent 52% of annual revenue.",
                "Northwind's single largest customer represents 26% of revenue.",
            ],
        },
    ],
    "stellar logistics": [
        {
            "title": "filing vs. independent-data divergence",
            "description": (
                "Filed +18% revenue growth conflicts with a carrier survey suggesting "
                "revenue per route declined 7% in Q3. The reconciliation is unresolved "
                "and is itself a material diligence risk."
            ),
            "severity": "high",
            "related_claim_texts": [
                "Stellar Logistics revenue grew 18% YoY per the annual filing.",
                "Independent carrier survey suggests Stellar revenue per route declined 7% in Q3.",
            ],
        },
    ],
    "pinecone bio": [
        {
            "title": "FDA manufacturing controls gating IND",
            "description": (
                "FDA has flagged manufacturing controls as requiring resolution before "
                "the lead program (PCB-101) can file IND. Combined with the limited cash "
                "runway, this materially raises execution risk."
            ),
            "severity": "high",
            "related_claim_texts": [
                "FDA pre-IND correspondence flagged Pinecone's manufacturing controls as requiring resolution before IND filing.",
                "Pinecone Bio's cash runway extends through Q2 of next year at current burn; a financing round is likely required to reach IND filing.",
            ],
        },
    ],
}


# ---------------------------------------------------- memo bodies
#
# These are the final canned memos returned by the recorded provider
# when memo_synthesizer fires. The handler resolves text references
# back to live object ids via the graph; the structure here matches
# what the test asserts. The handler also fills evidence_ids /
# claim_ids from the live graph after-the-fact (NOT in v0.9 — for
# simplicity we just have the LLM "produce" plausible structure that
# the post-write integration test verifies against the live graph
# via separate predicates).

MEMO_BODIES_BY_COMPANY = {
    "northwind robotics": {
        "summary": (
            "Northwind Robotics shows healthy +28% YoY top-line growth with stable "
            "41% gross margin. The picture is bottlenecked by single-customer "
            "concentration (26% from the largest account, 52% from the top three). "
            "Product roadmap (NW-7 cobot in food-and-beverage) is incremental and "
            "credible. Recommendation: pass unless concentration risk can be diligenced "
            "to the satisfaction of the IC."
        ),
        "thesis_questions_addressed": [
            {"question": "Q3 revenue trajectory", "status": "answered", "claim_ids": ["@claim:Q3 revenue"]},
            {"question": "Customer concentration", "status": "answered", "claim_ids": ["@claim:top three", "@claim:largest customer"]},
            {"question": "Gross margin", "status": "answered", "claim_ids": ["@claim:Q3 gross margin"]},
            {"question": "Roadmap", "status": "answered", "claim_ids": ["@claim:NW-7 launch"]},
        ],
        "key_claims": [
            {"claim_id": "@claim:Q3 revenue", "text": "Northwind Q3 revenue grew 28% YoY to $42M.", "evidence_ids": ["@evidence:Q3 revenue quote"]},
            {"claim_id": "@claim:top three", "text": "Top three customers represent 52% of revenue.", "evidence_ids": ["@evidence:top three quote"]},
            {"claim_id": "@claim:largest customer", "text": "Single largest customer represents 26% of revenue.", "evidence_ids": ["@evidence:largest customer quote"]},
            {"claim_id": "@claim:Q3 gross margin", "text": "Q3 gross margin was 41%.", "evidence_ids": ["@evidence:gross margin quote"]},
        ],
        "open_contradictions": [],
        "contradictions_note": "no contradictions found",
        "risks": [
            {"risk_id": "@risk:concentration", "title": "customer concentration", "severity": "high",
             "description": "Loss of the largest customer (26%) would materially impair financials."},
        ],
    },
    "stellar logistics": {
        "summary": (
            "Stellar Logistics filings report +18% YoY revenue growth and 14-metro "
            "coverage; an independent carrier survey suggests revenue per route declined "
            "7% in Q3 — a material contradiction that requires reconciliation before "
            "any investment decision."
        ),
        "thesis_questions_addressed": [
            {"question": "Revenue growth rate", "status": "answered", "claim_ids": ["@claim:filing growth", "@claim:survey decline"]},
            {"question": "Metro coverage", "status": "answered", "claim_ids": ["@claim:14 metros"]},
            {"question": "Filing vs. independent data divergence", "status": "answered", "claim_ids": ["@claim:filing growth", "@claim:survey decline"]},
            {"question": "Management guidance", "status": "answered", "claim_ids": ["@claim:management guidance"]},
        ],
        "key_claims": [
            {"claim_id": "@claim:filing growth", "text": "Stellar Logistics revenue grew 18% YoY per the annual filing.", "evidence_ids": ["@evidence:filing quote"]},
            {"claim_id": "@claim:survey decline", "text": "Independent carrier survey suggests Stellar revenue per route declined 7% in Q3.", "evidence_ids": ["@evidence:survey quote"]},
            {"claim_id": "@claim:14 metros", "text": "Stellar's network covers 14 metros, with positive unit economics in 9 of them.", "evidence_ids": ["@evidence:metros quote"]},
            {"claim_id": "@claim:management guidance", "text": "Management guides for 20% YoY revenue growth through next year.", "evidence_ids": ["@evidence:guidance quote"]},
        ],
        "open_contradictions": [
            {"contradiction_id": "@contradiction:growth", "claim_a_text": "Stellar Logistics revenue grew 18% YoY per the annual filing.", "claim_b_text": "Independent carrier survey suggests Stellar revenue per route declined 7% in Q3."},
        ],
        "contradictions_note": "",
        "risks": [
            {"risk_id": "@risk:divergence", "title": "filing vs. independent-data divergence", "severity": "high",
             "description": "Filed growth conflicts with carrier-survey data. Unresolved and itself a material risk."},
        ],
    },
    "pinecone bio": {
        "summary": (
            "Pinecone Bio's lead asset PCB-101 is on a credible IND trajectory but "
            "blocked by FDA-flagged manufacturing controls. Cash runway through Q2 "
            "next year is materially tight; a financing round is likely required "
            "before the IND filing. Recommendation: monitor; revisit after CMC "
            "resolution and pre-IND financing event."
        ),
        "thesis_questions_addressed": [
            {"question": "Lead program regulatory status", "status": "answered", "claim_ids": ["@claim:PCB-101 IND"]},
            {"question": "FDA pre-IND meeting", "status": "answered", "claim_ids": ["@claim:FDA CMC flag"]},
            {"question": "Cash runway", "status": "answered", "claim_ids": ["@claim:runway"]},
        ],
        "key_claims": [
            {"claim_id": "@claim:PCB-101 IND", "text": "PCB-101 is targeted for IND filing in H2 of next year.", "evidence_ids": ["@evidence:PCB-101 quote"]},
            {"claim_id": "@claim:FDA CMC flag", "text": "FDA pre-IND correspondence flagged Pinecone's manufacturing controls as requiring resolution before IND filing.", "evidence_ids": ["@evidence:FDA quote"]},
            {"claim_id": "@claim:runway", "text": "Pinecone Bio's cash runway extends through Q2 of next year at current burn; a financing round is likely required to reach IND filing.", "evidence_ids": ["@evidence:runway quote"]},
        ],
        "open_contradictions": [],
        "contradictions_note": "no contradictions found",
        "risks": [
            {"risk_id": "@risk:CMC", "title": "FDA manufacturing controls gating IND", "severity": "high",
             "description": "FDA-flagged CMC issues combine with tight cash runway. Material execution risk."},
        ],
    },
}
