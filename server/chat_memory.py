import re
import sqlite3
import json
from contextlib import closing


STOP_WORDS = set(
    "about again also and are can could did does for from had has have how into "
    "just more please should tell than that the their them then there these they "
    "this use used using want was were what when where which who why will with would you your".split()
)


class ChatMemory:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5("
                "conversation UNINDEXED, turn UNINDEXED, prompt, reply, summary UNINDEXED)"
            )
            db.executescript("""
                CREATE TABLE IF NOT EXISTS turn_metadata (
                    rowid INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source TEXT NOT NULL, kind TEXT NOT NULL, importance INTEGER NOT NULL,
                    sources TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_state (
                    conversation TEXT PRIMARY KEY, state TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    turn_rowid INTEGER PRIMARY KEY, review TEXT NOT NULL
                );
            """)

    def latest(self, conversation):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT summary FROM turns WHERE conversation = ? ORDER BY rowid DESC LIMIT 1",
                (conversation,),
            ).fetchone()
        return row[0] if row else ""

    def remember(self, conversation, turn, prompt, reply, summary, sources=(), state=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT summary FROM turns WHERE conversation = ? AND turn = ?", (conversation, turn)
            ).fetchone()
            if existing:
                summary = existing[0]
            else:
                cursor = db.execute("INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
                                    (conversation, turn, prompt, reply, summary))
                kind = "research" if sources else "turn"
                if re.search(r"\b(?:prefer|preference)\b", prompt, re.I):
                    kind = "preference"
                elif re.search(r"\b(?:decided|decision)\b", prompt, re.I):
                    kind = "decision"
                elif re.search(r"\b(?:remember|must|require|constraint)\b", prompt, re.I):
                    kind = "fact"
                elif state and state.get("completed"):
                    kind = "task_result"
                important = kind in ("preference", "decision", "fact")
                db.execute(
                    "INSERT INTO turn_metadata(rowid, source, kind, importance, sources) VALUES (?, ?, ?, ?, ?)",
                    (cursor.lastrowid, "chat", kind, 2 if important else 1, json.dumps(sources)),
                )
                if state is not None:
                    db.execute(
                        "INSERT INTO task_state(conversation, state) VALUES (?, ?) "
                        "ON CONFLICT(conversation) DO UPDATE SET state=excluded.state, updated_at=CURRENT_TIMESTAMP",
                        (conversation, json.dumps(state)),
                    )
            count = db.execute("SELECT count(*) FROM turns WHERE conversation = ?", (conversation,)).fetchone()[0]
        return summary, count

    def state(self, conversation):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT state FROM task_state WHERE conversation=?", (conversation,)).fetchone()
        return json.loads(row[0]) if row else {}

    def recent(self, conversation, limit=4):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT rowid, prompt, reply FROM turns WHERE conversation=? ORDER BY rowid DESC LIMIT ?",
                (conversation, limit),
            ).fetchall()

    def conversations(self):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("""
                SELECT grouped.conversation, substr(first_turn.prompt, 1, 100)
                FROM (
                    SELECT conversation, min(rowid) AS first_id, max(rowid) AS last_id
                    FROM turns GROUP BY conversation
                ) AS grouped JOIN turns AS first_turn ON first_turn.rowid = grouped.first_id
                ORDER BY grouped.last_id DESC
            """).fetchall()
        return [{"id": conversation, "title": title} for conversation, title in rows]

    def transcript(self, conversation):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("""
                SELECT turns.turn, turns.prompt, turns.reply, turns.summary, metadata.sources, reviews.review
                FROM turns LEFT JOIN turn_metadata AS metadata ON metadata.rowid = turns.rowid
                LEFT JOIN reviews ON reviews.turn_rowid = turns.rowid
                WHERE turns.conversation = ? ORDER BY turns.rowid
            """, (conversation,)).fetchall()
            state = db.execute("SELECT state FROM task_state WHERE conversation = ?", (conversation,)).fetchone()
        return {
            "conversation": conversation,
            "summary": rows[-1][3] if rows else "",
            "taskState": json.loads(state[0]) if state else {},
            "archivedTurns": len(rows),
            "turns": [
                {"id": turn, "prompt": prompt, "answer": reply, "sources": json.loads(sources) if sources else [],
                 "review": json.loads(review) if review else None}
                for turn, prompt, reply, _, sources, review in rows
            ],
            "pending": False,
        }

    def review_target(self, conversation, turn):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT rowid, prompt, reply FROM turns WHERE conversation=? AND turn=?",
                (conversation, turn),
            ).fetchone()

    def save_review(self, rowid, review):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO reviews(turn_rowid, review) VALUES (?, ?) "
                "ON CONFLICT(turn_rowid) DO UPDATE SET review=excluded.review",
                (rowid, json.dumps(review)),
            )

    def recorded_summary(self, conversation, turn):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT summary FROM turns WHERE conversation=? AND turn=?", (conversation, turn)
            ).fetchone()
        return row[0] if row else None

    def source(self, conversation, reference):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT metadata.sources FROM turn_metadata metadata JOIN turns ON turns.rowid=metadata.rowid "
                "WHERE turns.conversation=? AND metadata.rowid=?",
                (conversation, reference),
            ).fetchone()
        return json.loads(row[0]) if row else []

    def recall(self, conversation, prompt, exclude=()):
        words = dict.fromkeys(
            word for word in re.findall(r"[^\W_]{3,}", prompt.lower())
            if word not in STOP_WORDS
        )
        terms = " OR ".join(f'"{word}"' for word in list(words)[:24])
        if not terms:
            return []
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT turns.rowid, snippet(turns, 2, '', '', ' … ', 24), "
                "snippet(turns, 3, '', '', ' … ', 36) "
                "FROM turns LEFT JOIN turn_metadata metadata ON metadata.rowid=turns.rowid "
                "WHERE turns MATCH ? AND conversation = ? "
                "ORDER BY bm25(turns, 0, 0, 2, 1) * coalesce(metadata.importance, 1) * "
                "(1.0 + 0.25 / (1 + (SELECT max(rowid) FROM turns WHERE conversation = ?) - turns.rowid)), "
                "turns.rowid DESC LIMIT 6",
                (terms, conversation, conversation),
            ).fetchall()
        return [
            f"Memory {rowid}\nEarlier user: {prompt[:220]}\nEarlier reply: {reply[:320]}"
            for rowid, prompt, reply in rows if rowid not in exclude
        ][:3]
