"""Diligence pack tools. CONTRACT v0.9 #15.

Three pack-scoped tools backed by recorded fixtures. Production users
swap these for real implementations:
  - fetch_company_docs: would call a real fetcher (SEC, news APIs, etc.)
  - search_filings: would query EDGAR or a similar service
  - summarize_document: an LLM-backed summarizer with caching

The fixtures live in `activegraph.packs.diligence.fixtures` per
CONTRACT v0.9 #18 (fixtures ship with the pack).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from activegraph.packs import tool


# ---------------------------------------------------- I/O schemas


class FetchCompanyDocsInput(BaseModel):
    company_name: str
    max_results: int = 5


class DocumentRef(BaseModel):
    title: str
    url: str
    summary: str = ""


class FetchCompanyDocsOutput(BaseModel):
    documents: list[DocumentRef]


class SearchFilingsInput(BaseModel):
    company_name: str
    keyword: str = ""


class SearchFilingsOutput(BaseModel):
    filings: list[DocumentRef]


class SummarizeDocumentInput(BaseModel):
    url: str
    max_words: int = 100


class SummarizeDocumentOutput(BaseModel):
    summary: str
    extracted_facts: list[str] = []


# ---------------------------------------------------- tool registration


@tool(
    name="fetch_company_docs",
    description="Fetch a list of source documents for a company. "
                "Returns up to max_results documents with title, URL, "
                "and a one-line summary.",
    input_schema=FetchCompanyDocsInput,
    output_schema=FetchCompanyDocsOutput,
    cost_per_call=Decimal("0.005"),
    timeout_seconds=15.0,
    deterministic=False,
)
def fetch_company_docs(args: FetchCompanyDocsInput, ctx) -> FetchCompanyDocsOutput:
    """Backed by fixtures in v0.9. Production: real fetcher."""
    from activegraph.packs.diligence.fixtures import lookup_company_docs

    docs = lookup_company_docs(args.company_name, max_results=args.max_results)
    return FetchCompanyDocsOutput(
        documents=[DocumentRef(**d) for d in docs],
    )


@tool(
    name="search_filings",
    description="Search a company's regulatory filings by keyword. "
                "Returns matching filings as document refs.",
    input_schema=SearchFilingsInput,
    output_schema=SearchFilingsOutput,
    cost_per_call=Decimal("0.003"),
    timeout_seconds=15.0,
    deterministic=False,
)
def search_filings(args: SearchFilingsInput, ctx) -> SearchFilingsOutput:
    """Backed by fixtures in v0.9. Production: EDGAR query."""
    from activegraph.packs.diligence.fixtures import lookup_filings

    filings = lookup_filings(args.company_name, args.keyword)
    return SearchFilingsOutput(
        filings=[DocumentRef(**f) for f in filings],
    )


@tool(
    name="summarize_document",
    description="Summarize a document at a given URL and extract key facts.",
    input_schema=SummarizeDocumentInput,
    output_schema=SummarizeDocumentOutput,
    cost_per_call=Decimal("0.002"),
    timeout_seconds=30.0,
    deterministic=False,
)
def summarize_document(args: SummarizeDocumentInput, ctx) -> SummarizeDocumentOutput:
    """Backed by fixtures in v0.9. Production: LLM summarizer."""
    from activegraph.packs.diligence.fixtures import lookup_summary

    result = lookup_summary(args.url)
    return SummarizeDocumentOutput(
        summary=result.get("summary", "")[: args.max_words * 8],  # rough char cap
        extracted_facts=result.get("facts", []),
    )


TOOLS = [fetch_company_docs, search_filings, summarize_document]
