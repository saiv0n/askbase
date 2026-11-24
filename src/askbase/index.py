from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .ingest import Chunk

SCHEMA = """
create virtual table if not exists chunks using fts5(
    source unindexed, title, heading, text,
    tokenize = "unicode61 remove_diacritics 2"
);
create table if not exists questions (
    id integer primary key,
    asked_at text not null,
    question text not null,
    answered integer not null,
    top_source text
);
"""

# words that only add noise to a keyword search
STOP = set("""
a an and are as at be but by can could do does for from had has have how i if in is it its
me my of on or our please so that the their them then there these they this to us was we
were what when where which who why will with would you your
bir ve ile için mi mı mu mü ne nasıl neden nerede hangi bu şu o da de ki ben biz siz
""".split())

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Hit:
    source: str
    title: str
    heading: str
    text: str
    score: float


def to_query(question: str) -> str:
    """Turn free text into an FTS5 OR query with prefix matching.

    Prefixes make 'refund' match 'refunds' and 'kargo' match 'kargonuz', which
    matters a lot for languages with suffixes, like Turkish.
    """
    terms = []
    for w in _WORD.findall(question.lower()):
        if w in STOP or len(w) < 2:
            continue
        stem = w[:max(4, len(w) - 2)] if len(w) > 5 else w
        terms.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(terms))


class Index:
    def __init__(self, path: str | Path = "askbase.db"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def clear(self):
        self.db.execute("delete from chunks")
        self.db.commit()

    def add(self, chunks: list[Chunk]) -> int:
        self.db.executemany(
            "insert into chunks(source, title, heading, text) values (?, ?, ?, ?)",
            [(c.source, c.title, c.heading, c.text) for c in chunks],
        )
        self.db.commit()
        return len(chunks)

    def count(self) -> int:
        return self.db.execute("select count(*) from chunks").fetchone()[0]

    def search(self, question: str, k: int = 5) -> list[Hit]:
        q = to_query(question)
        if not q:
            return []
        # heading and title matches weigh more than body text
        rows = self.db.execute(
            "select source, title, heading, text, bm25(chunks, 0, 4.0, 3.0, 1.0) as s "
            "from chunks where chunks match ? order by s limit ?",
            (q, k),
        ).fetchall()
        return [Hit(*r[:4], score=-r[4]) for r in rows]

    def log_question(self, question: str, answered: bool, top_source: str | None):
        self.db.execute(
            "insert into questions(asked_at, question, answered, top_source) values (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), question, int(answered), top_source),
        )
        self.db.commit()

    def questions(self, unanswered_only: bool = False) -> list[tuple]:
        sql = "select asked_at, question, answered, top_source from questions"
        if unanswered_only:
            sql += " where answered = 0"
        return self.db.execute(sql + " order by id").fetchall()
