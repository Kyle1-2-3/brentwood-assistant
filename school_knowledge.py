"""Search reviewed website facts and curated club summaries; no live inbox access."""
from collections import Counter
from functools import lru_cache
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "data" / "school_knowledge.json"
CLUB_KNOWLEDGE_PATH = Path(__file__).resolve().parent / "data" / "student_clubs.json"
STOPWORDS = set("a an the is are was were who what when how where why which can do does i my me you your about at of on in for to and or with school brentwood please tell have has it there".split())
ALIASES = {"math": "mathematics", "maths": "mathematics", "hiuse": "house",
           "whittal": "whittall", "mack": "mackenzie", "alex": "alexandra",
           "mr": "", "mrs": "", "ms": "", "facilities": "facility",
           "teachers": "teacher", "coaches": "coach", "houseparents": "houseparent",
           "sports": "sport", "arts": "art", "wifi": "wifi", "clubs": "club"}
PLACE_NAMES = set("foote crooks maeda killy bunch mcneill innovations rogers allard hope alexandra mackenzie privett ellis whittall".split())
CLUB_NAMES = {"sac", "bwell", "bipoc", "womenssociety", "beat", "omni"}


def tokens(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"house\s+parents?", "houseparent", text)
    text = re.sub(r"wi[ -]fi", "wifi", text)
    text = re.sub(r"\bb[\s-]*well\b", "bwell", text)
    text = re.sub(r"\bwomen(?:['’]s|s)?\s+society\b", "womenssociety", text)
    return [ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]+", text)
            if t not in STOPWORDS and ALIASES.get(t, t)]


@lru_cache(maxsize=1)
def load_knowledge():
    try:
        data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        records = data["records"]
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        # Keep the website snapshot's date; each curated club record carries its
        # own review date and email citation labels, without private inbox links.
        try:
            clubs = json.loads(CLUB_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
            club_records = clubs["records"]
            if not isinstance(club_records, list):
                raise ValueError("club records must be a list")
            records.extend({**r, "checked_on": clubs["checked_on"]} for r in club_records)
        except (OSError, ValueError, KeyError):
            logging.getLogger("chatbot").exception("Curated club information is unavailable")
        return data
    except (OSError, ValueError, KeyError):
        logging.getLogger("chatbot").exception("Public school knowledge is unavailable")
        return {"checked_on": None, "records": []}


_index_cache = (None, None)  # (knowledge dict, index) — rebuilt when the snapshot changes


def _index(data):
    """Tokenised records plus corpus statistics, built once per loaded snapshot."""
    global _index_cache
    if _index_cache[0] is not data:
        records = data["records"]
        docs = [Counter(tokens(r["title"] + " " + " ".join(r.get("keywords", []))
                               + " " + " ".join(r["facts"]))) for r in records]
        titles = [set(tokens(r["title"])) for r in records]
        named_terms = PLACE_NAMES | CLUB_NAMES | {t for r in records if r.get("category") == "staff"
                                    for t in tokens(r["title"]) if len(t) > 2}
        frequency = Counter(t for doc in docs for t in doc)
        average_length = sum(sum(d.values()) for d in docs) / len(docs)
        _index_cache = (data, (docs, titles, named_terms, frequency, average_length))
    return _index_cache[1]


def search_school_knowledge(search_query, limit=8):
    """Bounded lexical retrieval with title weighting and no unrelated fallback."""
    data = load_knowledge()
    records = data["records"]
    terms = set(tokens(search_query))
    if not terms or not records:
        return []
    docs, titles, named_terms, frequency, average_length = _index(data)
    anchors = terms & named_terms
    scored = []
    for record, doc, title in zip(records, docs, titles):
        matches = terms & doc.keys()
        if not matches or (anchors and not anchors.intersection(doc)):
            continue
        length = sum(doc.values())
        score = 0
        for term in matches:
            idf = math.log(1 + (len(docs) - frequency[term] + .5) / (frequency[term] + .5))
            tf = doc[term]
            score += idf * (tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average_length)))
            if term in title:
                score += idf * 1.5
        score *= len(matches) / len(terms)
        # A current club profile should precede an older website mention. For a
        # broad club question, start with the reviewed directory, not a sports
        # facility whose title happens to contain "club".
        preferred = record.get("source_type") == "curated_club_email" and (
            bool(terms & CLUB_NAMES & title)
            or ("club" in terms and not anchors
                and record["id"] == "student-club-info-2026-27")
        )
        scored.append((score, record, preferred))
    scored.sort(key=lambda pair: (pair[2], pair[0]), reverse=True)
    if not scored:
        return []
    cutoff = max(.1, max(pair[0] for pair in scored) * .22)
    return [{**record, "checked_on": record.get("checked_on", data["checked_on"])}
            for score, record, preferred in scored[:max(1, min(limit, 12))]
            if preferred or score >= cutoff]
