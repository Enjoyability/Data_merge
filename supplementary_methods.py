"""Supplementary Code S1. Selected bibliographic harmonization algorithms.

Extracted from the project source on 2026-09-23; original function bodies retained.
This is a selective methodological excerpt, not the complete processing pipeline.
See README.md for scope, original behavior, and interpretation of the example.
Run with Python 3.10 or later: python supplementary_methods.py
Only the Python standard library is required. All example records are synthetic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple



# Selected definitions from models.py


@dataclass
class Record:
    """
    WOS plain text record:
      tag -> list of logical lines (without leading tag/indent).
    """
    tags: Dict[str, List[str]] = field(default_factory=dict)
    source: str = "unknown"  # "wos" or "scopus"
    raw_index: Optional[int] = None  # for progress/debug

    def add(self, tag: str, content: str) -> None:
        tag = tag.strip()
        content = content.rstrip()
        self.tags.setdefault(tag, []).append(content)

    def get_first(self, tag: str) -> str:
        vals = self.tags.get(tag, [])
        return vals[0] if vals else ""

    def get_all(self, tag: str) -> List[str]:
        return list(self.tags.get(tag, []))

    def set_single(self, tag: str, value: str) -> None:
        self.tags[tag] = [value]

    def set_list(self, tag: str, values: List[str]) -> None:
        self.tags[tag] = list(values)


# Selected definitions from utils.py


def normalize_doi(doi: str) -> str:
    doi = doi.strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("https://dx.doi.org/", "").replace("http://dx.doi.org/", "")
    doi = doi.strip().strip(".").strip()
    return doi.lower()


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"\s+", " ", t)
    # remove punctuation-ish to improve matching stability
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def join_lines(lines: Iterable[str]) -> str:
    s = " ".join([x.strip() for x in lines if x.strip()])
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Selected definitions from mappers.py


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>\]]+\b", re.IGNORECASE)


_DOI_TOKEN_FIX_RE = re.compile(r"\bdoi\s*[:=]?\s*", re.IGNORECASE)


_PRIMARY_AFFILIATION_KEYWORD_RE = re.compile(
    r"\b(?:univ(?:ersity)?|hospital|colleges?|medical\s+center|medical\s+centre|health\s+system)\b",
    re.IGNORECASE,
)


_ADDRESS_LIKE_SEGMENT_RE = re.compile(
    r"\b(?:road|street|avenue|boulevard|lane|drive|district|building|room|floor)\b",
    re.IGNORECASE,
)


_SECONDARY_AFFILIATION_KEYWORD_RE = re.compile(
    r"\b(?:department|dept\.?|school|faculty|division|section)\b",
    re.IGNORECASE,
)


_COLLEGE_OF_UNIT_RE = re.compile(
    r"\bcollege\s+of\s+[A-Za-z][\w'&/-]*\b",
    re.IGNORECASE,
)


_UNIVERSITY_AFFILIATION_RE = re.compile(
    r"\buniv(?:ersity)?\b",
    re.IGNORECASE,
)


_HOSPITAL_AFFILIATION_RE = re.compile(
    r"\bhospital\b",
    re.IGNORECASE,
)


def normalize_spaces(s: str) -> str:
    return " ".join((s or "").strip().split())


def extract_doi_from_text(text: str) -> Optional[str]:
    m = _DOI_RE.search(text or "")
    return normalize_doi(m.group(0)) if m else None


def ensure_record_doi(rec: Record) -> Optional[str]:
    """
    Ensure DOI is stored in WOS tag DI.
    Returns the normalized DOI if found, otherwise None.
    """
    di_vals = rec.get_all("DI")
    if di_vals:
        di = normalize_spaces(di_vals[0])
        di = _DOI_TOKEN_FIX_RE.sub("", di).strip().strip(".").strip(",").strip(";")
        di = normalize_doi(di)
        rec.set_list("DI", [di])
        return di or None

    for alt in ("DOI", "DO"):
        vals = rec.get_all(alt)
        if vals:
            di = normalize_spaces(vals[0])
            di = _DOI_TOKEN_FIX_RE.sub("", di).strip().strip(".").strip(",").strip(";")
            di = normalize_doi(di)
            rec.set_list("DI", [di])
            return di or None

    for tag in ("AB", "TI", "SO", "RP", "C1", "CR", "NR", "N1", "FU", "FX", "EM"):
        for value in rec.get_all(tag):
            doi = extract_doi_from_text(value)
            if doi:
                rec.set_list("DI", [doi])
                return doi

    return None


def _clean_affiliation_display(affiliation: str) -> str:
    return normalize_spaces(affiliation).strip().strip(",").rstrip(".")


def _split_affiliation_segments(affiliation: str) -> List[str]:
    return [
        normalize_spaces(segment).strip(",")
        for segment in (affiliation or "").split(",")
        if normalize_spaces(segment).strip(",")
    ]


def _is_primary_affiliation_segment(segment: str) -> bool:
    segment = normalize_spaces(segment)
    if not segment:
        return False

    if _ADDRESS_LIKE_SEGMENT_RE.search(segment):
        return False

    if re.search(r"\bno\.?\s*\d", segment, flags=re.IGNORECASE):
        return False

    return bool(_PRIMARY_AFFILIATION_KEYWORD_RE.search(segment))


def _promote_primary_affiliation_segment(affiliation: str) -> str:
    """
    Reorder comma-separated affiliation segments so the shortest institution-like
    segment (e.g. containing University/Hospital/College) comes first.

    This helps downstream software recognize the top-level institution from C1/C3
    instead of a department, faculty, or other sub-unit.
    """
    display = _clean_affiliation_display(affiliation)
    if not display:
        return ""

    segments = _split_affiliation_segments(display)
    if len(segments) <= 1:
        return display

    primary_candidates = [
        (idx, segment)
        for idx, segment in enumerate(segments)
        if _is_primary_affiliation_segment(segment)
    ]
    if not primary_candidates:
        return display

    primary_idx, primary_segment = min(primary_candidates, key=lambda item: (len(item[1]), item[0]))
    if primary_idx == 0:
        return display

    reordered_segments = [primary_segment]
    reordered_segments.extend(segment for idx, segment in enumerate(segments) if idx != primary_idx)
    return ", ".join(reordered_segments)


def _swap_leading_secondary_c1_segment(c1_item: str) -> str:
    """Move a University segment, or a leading sub-unit fallback, to primary position."""
    text = normalize_spaces(c1_item)
    close_idx = text.find("]")
    if close_idx < 0:
        return text

    prefix = text[: close_idx + 1]
    segments = _split_affiliation_segments(text[close_idx + 1 :])
    if len(segments) < 2:
        return text

    university_idx = next(
        (idx for idx, segment in enumerate(segments) if _UNIVERSITY_AFFILIATION_RE.search(segment)),
        None,
    )
    if university_idx is not None:
        if university_idx == 0:
            return text
        university_segment = segments.pop(university_idx)
        segments.insert(0, university_segment)
        return f"{prefix} {', '.join(segments)}"

    first_segment = segments[0]
    if not (
        _SECONDARY_AFFILIATION_KEYWORD_RE.search(first_segment)
        or _COLLEGE_OF_UNIT_RE.search(first_segment)
    ):
        return text

    preferred_idx = next(
        (idx for idx, segment in enumerate(segments[1:], start=1) if _HOSPITAL_AFFILIATION_RE.search(segment)),
        None,
    )
    if preferred_idx is None:
        preferred_idx = 1

    preferred_segment = segments.pop(preferred_idx)
    segments.insert(0, preferred_segment)
    return f"{prefix} {', '.join(segments)}"


def _extract_affiliation_text_from_c1_item(item: str) -> str:
    text = normalize_spaces(item).rstrip(".")
    if not text:
        return ""

    if text.startswith("["):
        close_idx = text.find("]")
        if close_idx >= 0:
            text = normalize_spaces(text[close_idx + 1 :])
    return text.rstrip(".").strip()


def _derive_c3_items_from_c1(c1_items: Iterable[str]) -> List[str]:
    """
    Build a lightweight C3 list from C1 items.
    C3 keeps institution names only (first comma token), de-duplicated.
    """
    out: List[str] = []
    seen = set()

    for item in c1_items:
        aff = _extract_affiliation_text_from_c1_item(item)
        if not aff:
            continue
        org = normalize_spaces(aff.split(",", 1)[0]).rstrip(".")
        if not org:
            continue
        key = org.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(org)

    return out


# Selected definitions from cleaners.py


@dataclass
class CleanStats:
    removed_no_doi: int = 0
    removed_internal_dups: int = 0
    conflicts_same_doi_diff_title: int = 0


def record_title_norm(rec: Record) -> str:
    ti = join_lines(rec.get_all("TI"))
    return normalize_title(ti)


def record_doi_norm(rec: Record) -> str:
    di = join_lines(rec.get_all("DI"))
    if not di:
        doi = ensure_record_doi(rec)
        return doi or ""
    return normalize_doi(di)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def clean_remove_no_doi(records: List[Record]) -> Tuple[List[Record], CleanStats]:
    stats = CleanStats()
    kept: List[Record] = []
    for r in records:
        doi = record_doi_norm(r)
        if not doi:
            stats.removed_no_doi += 1
            continue
        # store normalized DOI back
        r.set_single("DI", doi)
        kept.append(r)
    return kept, stats


def dedup_by_doi_and_title(records: List[Record], title_sim_threshold: float = 0.92) -> Tuple[List[Record], CleanStats]:
    """
    Dual validation:
      - treat as duplicate if DOI matches AND title is very similar (or normalized title equal)
      - if DOI matches but title differs a lot -> conflict, keep both (safer)
    """
    stats = CleanStats()
    seen: Dict[str, Record] = {}
    out: List[Record] = []

    for r in records:
        doi = record_doi_norm(r)
        t = record_title_norm(r)

        if doi in seen:
            t0 = record_title_norm(seen[doi])
            if t == t0 or similar(t, t0) >= title_sim_threshold:
                stats.removed_internal_dups += 1
                continue
            else:
                # same DOI but different title -> keep both (log as conflict)
                stats.conflicts_same_doi_diff_title += 1
                out.append(r)
                continue

        seen[doi] = r
        out.append(r)

    return out, stats


def cross_dedup_keep_wos_first(wos_records: List[Record], scopus_records: List[Record], title_sim_threshold: float = 0.92) -> Tuple[List[Record], int]:
    """
    Merge with preference: keep WOS native when duplicated.
    Duplicate definition: DOI matches AND title similar.
    Returns merged_records, cross_dup_count
    """
    wos_by_doi: Dict[str, Record] = {}
    for r in wos_records:
        doi = record_doi_norm(r)
        if doi:
            wos_by_doi[doi] = r

    merged = list(wos_records)
    cross_dups = 0

    for r in scopus_records:
        doi = record_doi_norm(r)
        if not doi:
            continue
        if doi in wos_by_doi:
            t = record_title_norm(r)
            t0 = record_title_norm(wos_by_doi[doi])
            if t == t0 or similar(t, t0) >= title_sim_threshold:
                cross_dups += 1
                continue
        merged.append(r)

    return merged, cross_dups


def synthetic_example() -> None:
    """Demonstrate the original cleaning order on fictitious records."""
    wos = [
        Record(tags={"TI": ["Synthetic alpha study"], "DI": ["10.1234/example-a"]}, source="wos"),
        Record(tags={"TI": ["Synthetic alpha study."], "DI": ["https://doi.org/10.1234/example-a"]}, source="wos"),
        Record(tags={"TI": ["Synthetic record without identifier"]}, source="wos"),
    ]
    scopus = [
        Record(tags={"TI": ["Synthetic alpha study"], "DI": ["10.1234/example-a"]}, source="scopus"),
        Record(tags={"TI": ["Synthetic beta study"], "DI": ["10.1234/example-b"]}, source="scopus"),
    ]
    # Scopus DOI recovery occurs during mapping before cleaning in the source.
    for record in scopus:
        ensure_record_doi(record)
    wos_kept, wos_missing = clean_remove_no_doi(wos)
    scopus_kept, scopus_missing = clean_remove_no_doi(scopus)
    wos_unique, wos_duplicates = dedup_by_doi_and_title(wos_kept, 0.92)
    scopus_unique, scopus_duplicates = dedup_by_doi_and_title(scopus_kept, 0.92)
    merged, cross_duplicates = cross_dedup_keep_wos_first(wos_unique, scopus_unique, 0.92)
    assert len(merged) == 2 and merged[0].source == "wos"
    assert wos_missing.removed_no_doi == 1
    assert wos_duplicates.removed_internal_dups == 1 and cross_duplicates == 1

    # In the full mapper, promotion precedes final C1 ordering; C3 uses that C1.
    affiliation = _promote_primary_affiliation_segment(
        "Department of Medicine, Example Hospital, Example University, Example City"
    )
    c1 = _swap_leading_secondary_c1_segment(f"[Example, Alice] {affiliation}.")
    c3 = _derive_c3_items_from_c1([c1])
    assert c3 == ["Example University"]
    print("Synthetic example passed: 2 retained records; 1 missing DOI removed;")
    print("1 within-source duplicate removed; 1 cross-source duplicate removed.")
    print("C1:", c1)
    print("C3:", "; ".join(c3))


if __name__ == "__main__":
    synthetic_example()
