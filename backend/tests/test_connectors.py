from app.services.acquisition.connectors import (
    FoundLink,
    canonical_url,
    drive_file_id,
    extract_links,
    parse_dspace_item,
    parse_dspace_search,
)
from app.services.course_pipeline import is_relevant

COURSE = {"code": "MAT201", "code_variants": ["MAT201", "MAT 201"], "title": "Partial Differential Equations and Complex Analysis"}


def test_ktunotes_links_with_labels(fixture_text):
    links = extract_links(fixture_text("ktunotes_mat201.html"), "https://ktunotes.in/x/")
    drive = [l for l in links if "drive.google.com" in l.url]
    assert len(drive) == 4
    labels = " | ".join(l.label for l in drive)
    for session in ("December 2020", "December 2021", "December 2022", "June 2023"):
        assert session in labels


def test_dspace_search_and_item(fixture_text):
    base = "http://202.88.225.92/xmlui"
    items = parse_dspace_search(fixture_text("dspace_search_mat201.html"), base, ["MAT201", "MAT 201"])
    titles = [t for _u, t in items]
    assert len(items) == 10  # curriculum documents in the same results are excluded
    assert any("JUNE 2026" in t for t in titles) and any("DECEMBER 2020" in t for t in titles)
    assert all(u.startswith("http://202.88.225.92/xmlui/handle/") for u, _ in items)
    bs = parse_dspace_item(fixture_text("dspace_item_8850.html"), "http://202.88.225.92/xmlui/handle/1/8850")
    assert len(bs) == 1 and bs[0].startswith("http://202.88.225.92/xmlui/bitstream/handle/1/8850/") and ".PDF" in bs[0]


def test_drive_ids_and_canonical():
    url = "https://drive.google.com/file/d/1Rg6a2tS8uDoWPPZW76Go1tW_HpLCFiWH/view?usp=drive_link"
    assert drive_file_id(url) == "1Rg6a2tS8uDoWPPZW76Go1tW_HpLCFiWH"
    assert canonical_url(url) == canonical_url("https://drive.google.com/uc?export=download&id=1Rg6a2tS8uDoWPPZW76Go1tW_HpLCFiWH")
    assert canonical_url("https://www.example.com/a/b.pdf") == canonical_url("https://example.com/a/b.pdf/")


def test_relevance_filter():
    ok = FoundLink("https://x.com/MAT201-Dec-2021.pdf", "MAT201 Dec 2021", None, "agy:q1")
    notes = FoundLink("https://x.com/m1.pdf", "Module 1 notes", None, "page:ktuassist.in")
    unrelated = FoundLink("https://x.com/brochure.pdf", "College brochure", None, "agy:q3")
    assert is_relevant(ok, COURSE)[0]
    assert not is_relevant(notes, COURSE)[0]
    assert not is_relevant(unrelated, COURSE)[0]


def test_relevance_uses_links_own_text():
    c = {"code": "MAT202", "code_variants": ["MAT202", "MAT 202"], "title": "Probability, Statistics And Numerical Methods"}
    window = "MAT202_B.Tech_s4_Probability Statistics_July 2021 MAT204_B.Tech_s4_Random Processes"
    old_scheme = FoundLink("https://x.org/f/ma202-may2017.pdf", window + " B.Tech-S4-MA202-Probability Distributions May 2017",
                           None, "agy:q3>page", near="B.Tech-S4-MA202-Probability Distributions May 2017")
    mine = FoundLink("https://x.org/f/abc.pdf", window, None, "agy:q3>page", near="MAT202_B.Tech_s4_Probability July 2021")
    no_code = FoundLink("https://x.org/f/x.pdf", "Download", None, "agy:q3>page", near="Download")
    assert not is_relevant(old_scheme, c)[0] and "another course" in is_relevant(old_scheme, c)[1]
    assert is_relevant(mine, c)[0]
    assert not is_relevant(no_code, c)[0]
    links = extract_links('<p>MAT202 June 2022</p><a href="/a.pdf">Download</a><p>MA202 May 2017</p><a href="/b.pdf">Download</a>',
                          "https://x.org/")
    assert "MAT202" in links[0].near and "MA202" not in links[0].near.replace("MAT202", "")
    assert "MA202" in links[1].near


def test_broad_mode_keeps_other_courses_but_not_notes():
    from app.services.course_pipeline import broad_relevant, is_relevant

    cdef = {"code": "MAT201", "code_variants": ["MAT201", "MAT 201"]}
    other = FoundLink("https://x.com/CST201-Dec-2022.pdf", "CST201 Data Structures Dec 2022", None, "agy:b1>page")
    notes = FoundLink("https://x.com/m2.pdf", "CST201 Module 2 notes", None, "agy:b1>page")
    assert not is_relevant(other, cdef)[0]
    assert broad_relevant(other)[0]
    assert not broad_relevant(notes)[0]


def test_library_code_and_queries():
    from app.services.library import library_queries, norm_code

    assert norm_code("MAT 201") == "MAT201" and norm_code("cst-201 notes") == "CST201" and norm_code("hello") is None
    own = library_queries("CST201 data structures", "KTU", "APJ Abdul Kalam Technological University", "2019", "CSE", 3)
    wide = library_queries(None, "KTU", "APJ Abdul Kalam Technological University", "2019", "CSE", 3)
    assert len(own) >= 6 and len(wide) >= 6 and own[0][0] == "CST201 data structures"
    assert all("S3" in q or "KTU" in q or "Kalam" in q for q, _ in wide)


def test_broad_mode_needs_a_paper_signal():
    from app.services.course_pipeline import broad_relevant

    junk = FoundLink("https://college.edu/uploads/obc.pdf", "OBC Committee Research and Development Cell", None, "agy:l1>page")
    paper = FoundLink("https://college.edu/q/x.pdf", "December 2022 Regular CST401 S7", None, "agy:l1>page")
    assert not broad_relevant(junk)[0] and broad_relevant(paper)[0]


def test_code_prefixes_in_query():
    from app.services.library import code_prefixes

    assert code_prefixes("KTU AI & Data Science (ADT)") == ["ADT"]
    assert code_prefixes("CST201 data structures") == []
    assert code_prefixes("KTU S4 CSE") == []
