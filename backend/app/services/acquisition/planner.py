"""
Discovery query planner — turns a course definition into a fan-out of web searches.

Queries vary the code spelling, the title wording, sessions, source types and site
hints so different search paths surface different hosts. Gap queries target sessions
the coverage matrix shows as missing.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedQuery:
    id: str
    text: str
    purpose: str


def plan_queries(
    course: dict, missing_labels: list[str] | None = None, minimum: int = 8, maximum: int = 12
) -> list[PlannedQuery]:
    """`minimum` core queries, then gap queries for missing sessions, capped at `maximum`."""
    code = course["code"]
    codes = course.get("code_variants") or [code]
    title = course["title"]
    titles = [title] + list(course.get("title_variants") or [])
    uni = course.get("university", "")
    uni_name = course.get("university_name", uni)
    scheme = course.get("scheme", "")
    sem = course.get("semester")
    alt_code = codes[1] if len(codes) > 1 else code
    alt_title = titles[1] if len(titles) > 1 else title

    base = [
        PlannedQuery("q1", f'"{code}" "{title}" question paper pdf {uni} {scheme} scheme', "exact code + title"),
        PlannedQuery("q2", f'"{alt_code}" {alt_title} previous year university question papers', "code/title variants"),
        PlannedQuery("q3", f"{uni} S{sem} {scheme} scheme previous question papers {code} download" if sem else
                     f"{uni} {scheme} scheme previous question papers {code} download", "semester collections"),
        PlannedQuery("q4", f"{code} {title} question paper drive.google.com", "Google Drive hosted files"),
        PlannedQuery("q5", f"{code} {title} December regular examination question paper", "regular sessions"),
        PlannedQuery("q6", f"{code} {title} supplementary examination question paper May June", "supplementary sessions"),
        PlannedQuery("q7", f"{uni_name} {code} question paper DSpace OR library repository", "institutional repositories"),
        PlannedQuery("q8", f"{code} {uni} question papers ktunotes OR ktuassist OR keralanotes OR ktustudents", "student portals"),
        PlannedQuery("q9", f"{code} {title} solved question paper OR answer key OR scheme of valuation", "solved papers / keys"),
        PlannedQuery("q10", f'"{code}" question paper {scheme} scheme filetype:pdf', "direct PDFs"),
    ]
    gaps = [
        PlannedQuery(f"g{i + 1}", f"{code} {title} question paper {label}", f"gap: {label}")
        for i, label in enumerate(missing_labels or [])
    ]
    core = base[: max(minimum, 1)]
    queries = core + gaps[: max(0, maximum - len(core))]
    # Few gaps: use the remaining budget on the extra core queries.
    return queries + base[len(core) : len(core) + max(0, maximum - len(queries))] if len(queries) < maximum else queries


SCOUT_PROMPT = """Find downloadable previous-year university question papers.

Course: {code} — {title}
University: {university_name} ({scheme} scheme)
Search query to run first: {query}
Purpose of this query: {purpose}

Run the query with search_web, then up to two close variations of it. You cannot open
pages: report the URLs that appear in the search results (the app opens listing pages
and collects their download links itself). Never construct or guess URLs.

Reply with only this JSON:
{{"candidates": [{{"url": "<direct file link or listing page URL>", "page_url": "<page where you saw it, or null>", "label": "<text shown next to the link, e.g. exam month/year>", "kind": "pdf" | "drive" | "page"}}]}}
Use kind "page" for listing pages that contain several papers. Return an empty list if nothing relevant was found."""


def broad_queries(course: dict) -> list[PlannedQuery]:
    """Wide searches: same university/scheme/semester collections, not tied to this course's code."""
    uni = course.get("university", "")
    uni_name = course.get("university_name", uni)
    scheme = course.get("scheme", "")
    sem = course.get("semester")
    branch = course.get("branch") or ""
    s = f"S{sem} " if sem else ""
    return [
        PlannedQuery("b1", f"{uni} {scheme} scheme {s}question papers all subjects pdf", "broad: semester collections"),
        PlannedQuery("b2", f"{uni} {s}{branch} previous year question papers {scheme} scheme download".replace("  ", " "), "broad: branch collections"),
        PlannedQuery("b3", f"{uni_name} B.Tech {s}examination question papers repository", "broad: university repositories"),
        PlannedQuery("b4", f"{uni} {scheme} scheme question papers google drive folder", "broad: shared drives"),
        PlannedQuery("b5", f"{uni} {scheme} scheme {s}regular and supplementary question papers", "broad: all sessions"),
        PlannedQuery("b6", f"{uni} {scheme} scheme question bank previous papers {course['title']} related subjects", "broad: neighbouring subjects"),
    ]
