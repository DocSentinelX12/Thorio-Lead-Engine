import json
import sqlite3
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .agent_registry import agent_registry


class LeadDB:
    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "leads.sqlite3"
        self.recovered_corrupt_database = False
        self._batch_write_depth = 0
        self.conn = self._connect_with_recovery()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS leads (
            fingerprint TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
            collector TEXT PRIMARY KEY,
            checkpoint TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS agent_queue (
            task_id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            queue TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL,
            dedupe_key TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_until TEXT,
            worker_id TEXT,
            last_error TEXT,
            result TEXT,
            lease_token TEXT
        )""")
        try:
            self.conn.execute("ALTER TABLE agent_queue ADD COLUMN lease_token TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_queue_agent_status_priority ON agent_queue(agent, status, priority DESC, created_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_queue_dedupe ON agent_queue(agent, dedupe_key, status)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS compute_lead_work (
            fingerprint TEXT PRIMARY KEY,
            task_id TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            result TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_compute_lead_work_status ON compute_lead_work(status, updated_at)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS compute_bridge_publications (
            task_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prepared',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_compute_bridge_publications_status ON compute_bridge_publications(status, updated_at)")
        self.conn.commit()
        self._migrate_agent_queue_state()

    def _connect_with_recovery(self):
        if not self.path.exists():
            return sqlite3.connect(self.path, timeout=30)
        conn = None
        try:
            conn = sqlite3.connect(self.path, timeout=30)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and str(result[0]).lower() == "ok":
                return conn
        except sqlite3.DatabaseError:
            pass
        if conn is not None:
            try:
                conn.close()
            except sqlite3.DatabaseError:
                pass
        self._quarantine_corrupt_database()
        self.recovered_corrupt_database = True
        return sqlite3.connect(self.path, timeout=30)

    def _quarantine_corrupt_database(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for suffix in ("", "-wal", "-shm"):
            source = Path(f"{self.path}{suffix}")
            if source.exists():
                destination = Path(f"{self.path}.corrupt-{stamp}{suffix}")
                source.replace(destination)

    @contextmanager
    def batch_writes(self):
        self._batch_write_depth += 1
        try:
            yield self
        finally:
            self._batch_write_depth -= 1
            if self._batch_write_depth == 0:
                self.conn.commit()

    def insert_if_new(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            raise ValueError("Lead payload must be an object.")
        fingerprint = payload.get("fingerprint")
        if not fingerprint:
            raise ValueError("Lead payload must contain a fingerprint.")
        cursor = self.conn.execute("INSERT OR IGNORE INTO leads (fingerprint, payload) VALUES (?, ?)", (str(fingerprint), json.dumps(payload, ensure_ascii=False)))
        if cursor.rowcount == 1:
            self.conn.execute(
                "INSERT OR IGNORE INTO compute_lead_work (fingerprint,status,attempts,last_error,result,created_at,updated_at) VALUES (?, 'queued', 0, '', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (str(fingerprint),),
            )
        if self._batch_write_depth == 0:
            self.conn.commit()
        return cursor.rowcount == 1

    def all_leads(self):
        rows = self.conn.execute("SELECT payload FROM leads ORDER BY rowid").fetchall()
        result = []
        for row in rows:
            payload = json.loads(row[0])
            if isinstance(payload, dict):
                result.append(payload)
        return result

    def get(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT payload FROM leads WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise ValueError("Stored lead payload must be an object.")
        return payload

    def update_payload(self, fingerprint: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(updates, dict):
            raise ValueError("Lead updates must be a dictionary.")
        current = self.get(fingerprint)
        if current is None:
            return None
        before = dict(current)
        current_state = str(current.get("revenue_lifecycle_state") or "").strip().lower()
        incoming_state = str(updates.get("revenue_lifecycle_state") or "").strip().lower()
        lifecycle_order = {
            "": 0,
            "discovered": 10,
            "researching": 20,
            "researched": 30,
            "qualifying": 40,
            "qualified": 50,
            "opportunity_identified": 60,
            "dedup_checked": 70,
            "sales_eligible": 80,
            "sales_queued": 90,
            "sales_active": 100,
            "outreach_sent": 110,
            "conversation_active": 120,
            "follow_up_due": 125,
            "converted": 200,
            "referred": 200,
            "closed_lost": 200,
            "disqualified": 200,
            "stopped": 200,
        }
        current_rank = lifecycle_order.get(current_state, 0)
        incoming_rank = lifecycle_order.get(incoming_state, 0) if incoming_state else 0
        protected_revenue_fields = ("revenue_lifecycle_state", "sales_eligibility", "sales_eligibility_reason", "eligible_routes", "preserved_routes", "outreach_state", "outreach_attempt", "next_follow_up_at", "follow_up_due", "conversation_id", "outreach_route", "active_route", "outreach_history", "conversation_events", "response_count", "last_response_at", "last_outreach_action_id", "last_outreach_delivery", "route_switch_history", "outreach_stop_reason")
        current.update(updates)
        if current_rank > incoming_rank and current_state:
            for field in protected_revenue_fields:
                if field in before:
                    current[field] = before[field]
                else:
                    current.pop(field, None)
        prior_action = str(before.get("last_outreach_action_id") or "").strip()
        incoming_action = str(updates.get("last_outreach_action_id") or "").strip()
        if prior_action and not incoming_action and "outreach_state" in updates:
            prior_response = str(before.get("last_response_at") or "").strip()
            incoming_response = str(updates.get("last_response_at") or "").strip()
            if not incoming_response or incoming_response <= prior_response:
                current["outreach_state"] = before.get("outreach_state")
        if current == before:
            return current
        self.conn.execute("UPDATE leads SET payload = ?, synced = 0, last_error = '', updated_at = CURRENT_TIMESTAMP WHERE fingerprint = ?", (json.dumps(current, ensure_ascii=False), fingerprint))
        if self._batch_write_depth == 0:
            self.conn.commit()
        return current

    def pending(self, limit=50):
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("Pending limit must be an integer.")
        if limit <= 0:
            raise ValueError("Pending limit must be greater than zero.")
        return self.conn.execute("SELECT fingerprint, payload, attempts FROM leads WHERE synced = 0 ORDER BY rowid LIMIT ?", (limit,)).fetchall()

    def compute_lead_pending(self, limit=50):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("Compute lead limit must be a positive integer.")
        rows = self.conn.execute(
            """SELECT w.fingerprint,w.task_id,w.status,w.attempts,w.last_error,w.result,l.payload
               FROM compute_lead_work w JOIN leads l ON l.fingerprint=w.fingerprint
               WHERE w.status IN ('queued','retry') ORDER BY w.created_at,w.fingerprint LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"fingerprint": r[0], "task_id": r[1], "status": r[2], "attempts": int(r[3]), "last_error": r[4], "result": json.loads(r[5]) if r[5] else None, "lead": json.loads(r[6])} for r in rows]

    def compute_lead_dispatched(self, limit=50):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("Compute lead limit must be a positive integer.")
        rows = self.conn.execute(
            """SELECT w.fingerprint,w.task_id,w.status,w.attempts,w.last_error,w.result,l.payload
               FROM compute_lead_work w JOIN leads l ON l.fingerprint=w.fingerprint
               WHERE w.status='dispatched' AND w.task_id IS NOT NULL ORDER BY w.updated_at,w.fingerprint LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"fingerprint": r[0], "task_id": r[1], "status": r[2], "attempts": int(r[3]), "last_error": r[4], "result": json.loads(r[5]) if r[5] else None, "lead": json.loads(r[6])} for r in rows]

    def compute_lead_mark_dispatched(self, fingerprint, task_id):
        self.conn.execute("UPDATE compute_lead_work SET task_id=?,status='dispatched',attempts=attempts+1,last_error='',updated_at=CURRENT_TIMESTAMP WHERE fingerprint=? AND status IN ('queued','retry')", (str(task_id), str(fingerprint)))
        self.conn.commit()

    def compute_lead_mark_retry(self, fingerprint, error):
        self.conn.execute("UPDATE compute_lead_work SET status='retry',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE fingerprint=?", (str(error)[:4000], str(fingerprint)))
        self.conn.commit()

    def compute_lead_mark_completed(self, fingerprint, result):
        self.conn.execute("UPDATE compute_lead_work SET status='completed',result=?,last_error='',updated_at=CURRENT_TIMESTAMP WHERE fingerprint=?", (json.dumps(result, ensure_ascii=False), str(fingerprint)))
        self.conn.commit()

    def pending_research(self, limit=50):
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("Pending limit must be an integer.")
        if limit <= 0:
            raise ValueError("Pending limit must be greater than zero.")
        state = self.get_state("paxus_research_queue") or {}
        items = state.get("items", {})
        if not isinstance(items, dict):
            return []
        result = []
        for fingerprint, item in items.items():
            if not isinstance(item, dict):
                continue
            lead = self.get(str(fingerprint))
            if lead is None:
                continue
            result.append({**item, "lead": lead})
            if len(result) >= limit:
                break
        return result

    def get_sync_state(self, fingerprint: str) -> Dict[str, Any]:
        row = self.conn.execute("SELECT synced, attempts, last_error, updated_at FROM leads WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if row is None:
            raise ValueError(f"Lead not found: {fingerprint}")
        return {"synced": bool(row[0]), "attempts": int(row[1]), "last_error": str(row[2] or ""), "updated_at": row[3]}

    def mark_synced(self, fingerprint):
        self.conn.execute("UPDATE leads SET synced = 1, last_error = '', updated_at = CURRENT_TIMESTAMP WHERE fingerprint = ?", (fingerprint,))
        self.conn.commit()

    def mark_error(self, fingerprint, error):
        self.conn.execute("UPDATE leads SET synced = 0, attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE fingerprint = ?", (str(error)[:4000], fingerprint))
        self.conn.commit()

    def set_checkpoint(self, collector, checkpoint):
        if not collector:
            raise ValueError("Checkpoint collector is required.")
        if checkpoint is None:
            raise ValueError("Checkpoint value is required.")
        self.conn.execute("INSERT INTO checkpoints (collector, checkpoint) VALUES (?, ?) ON CONFLICT(collector) DO UPDATE SET checkpoint = excluded.checkpoint, updated_at = CURRENT_TIMESTAMP", (str(collector), str(checkpoint)))
        self.conn.commit()

    def get_checkpoint(self, collector):
        row = self.conn.execute("SELECT checkpoint FROM checkpoints WHERE collector = ?", (collector,)).fetchone()
        return row[0] if row else ""

    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if row:
            value = json.loads(row[0])
            if not isinstance(value, dict):
                raise ValueError("Stored state value must be an object.")
            return value
        if key == "agent_work_queue":
            rows = self.queue_all_rows()
            items = {str(row[0]): self._queue_row_to_dict(row) for row in rows}
            if items:
                return {"items": items}
        return None

    def set_state(self, key: str, value: Dict[str, Any]) -> None:
        if not key:
            raise ValueError("State key is required.")
        if not isinstance(value, dict):
            raise ValueError("State value must be an object.")
        self.conn.execute("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP", (key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def _migrate_agent_queue_state(self):
        row = self.conn.execute("SELECT COUNT(*) FROM agent_queue").fetchone()
        if row and int(row[0]) > 0:
            return
        legacy = self._get_state_raw("agent_work_queue")
        items = legacy.get("items", {}) if isinstance(legacy, dict) else {}
        if not isinstance(items, dict) or not items:
            return
        rows = []
        for task_id, task in items.items():
            if not isinstance(task, dict) or not task_id:
                continue
            rows.append((str(task_id), str(task.get("agent", "")), str(task.get("queue", "")), str(task.get("status", "queued")), int(task.get("priority", 0)), json.dumps(task.get("payload", {}), ensure_ascii=False), task.get("dedupe_key"), str(task.get("created_at", "")), str(task.get("updated_at", "")), int(task.get("attempts", 0)), task.get("lease_until"), task.get("worker_id"), task.get("last_error"), json.dumps(task.get("result"), ensure_ascii=False) if task.get("result") is not None else None, task.get("lease_token")))
        if rows:
            self.conn.executemany("INSERT OR IGNORE INTO agent_queue (task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self.conn.commit()

    def _get_state_raw(self, key):
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        value = json.loads(row[0])
        return value if isinstance(value, dict) else None

    def _queue_row_to_dict(self, row):
        return {"task_id": row[0], "agent": row[1], "queue": row[2], "status": row[3], "priority": row[4], "payload": json.loads(row[5]), "dedupe_key": row[6], "created_at": row[7], "updated_at": row[8], "attempts": row[9], "lease_until": row[10], "worker_id": row[11], "last_error": row[12], "result": json.loads(row[13]) if row[13] is not None else None, "lease_token": row[14]}

    def queue_insert_many(self, rows):
        normalized = [tuple(row) + (None,) if len(tuple(row)) == 14 else tuple(row) for row in rows]
        self.conn.executemany("INSERT OR IGNORE INTO agent_queue (task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", normalized)
        self.conn.commit()

    def queue_find_duplicate(self, agent, dedupe_key):
        if not dedupe_key:
            return None
        return self.conn.execute("SELECT task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token FROM agent_queue WHERE agent = ? AND dedupe_key = ? AND status IN ('queued', 'running') ORDER BY created_at LIMIT 1", (agent, dedupe_key)).fetchone()

    def queue_get(self, task_id):
        return self.conn.execute("SELECT task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token FROM agent_queue WHERE task_id = ?", (task_id,)).fetchone()

    def queue_recover_stale(self, now_iso):
        cursor = self.conn.execute("UPDATE agent_queue SET status = 'queued', worker_id = NULL, lease_until = NULL, lease_token = NULL, updated_at = ? WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?", (now_iso, now_iso))
        self.conn.commit()
        return cursor.rowcount > 0

    def queue_claim(self, agent, worker_id, limit, capacity, lease_until, now_iso):
        if limit <= 0 or capacity <= 0:
            return []
        role = agent_registry().get(agent)
        role_capacity = int(role.max_concurrency) if role is not None else int(capacity)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            running = int(self.conn.execute("SELECT COUNT(*) FROM agent_queue WHERE agent = ? AND status = 'running'", (agent,)).fetchone()[0])
            available = min(int(limit), int(capacity), max(0, role_capacity - running))
            if available <= 0:
                self.conn.commit()
                return []
            rows = self.conn.execute("SELECT task_id FROM agent_queue WHERE agent = ? AND status = 'queued' ORDER BY priority DESC, created_at LIMIT ?", (agent, available)).fetchall()
            claimed_ids = [row[0] for row in rows]
            if not claimed_ids:
                self.conn.commit()
                return []
            self.conn.executemany("UPDATE agent_queue SET status = 'running', worker_id = ?, lease_until = ?, lease_token = ?, attempts = attempts + 1, updated_at = ? WHERE task_id = ? AND status = 'queued'", [(worker_id, lease_until, uuid4().hex, now_iso, task_id) for task_id in claimed_ids])
            claimed = [task_id for task_id in claimed_ids if self.conn.execute("SELECT worker_id, status FROM agent_queue WHERE task_id = ?", (task_id,)).fetchone() == (worker_id, "running")]
            self.conn.commit()
            return [self.queue_get(task_id) for task_id in claimed]
        except Exception:
            self.conn.rollback()
            raise

    def queue_update(self, task_id, **updates):
        allowed = {"status", "updated_at", "lease_until", "worker_id", "attempts", "last_error", "result", "lease_token"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported queue fields: {sorted(unknown)}")
        if not updates:
            return
        assignments = ", ".join(f"{field} = ?" for field in updates)
        values = list(updates.values()) + [task_id]
        self.conn.execute(f"UPDATE agent_queue SET {assignments} WHERE task_id = ?", values)
        self.conn.commit()

    def queue_update_owned(self, task_id, expected_worker_id, expected_lease_token, **updates):
        allowed = {"status", "updated_at", "lease_until", "worker_id", "attempts", "last_error", "result", "lease_token"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported queue fields: {sorted(unknown)}")
        if not updates:
            return False
        assignments = ", ".join(f"{field} = ?" for field in updates)
        now_iso = datetime.now(timezone.utc).isoformat()
        values = list(updates.values()) + [task_id, expected_worker_id, expected_lease_token, now_iso]
        cursor = self.conn.execute(
            f"UPDATE agent_queue SET {assignments} WHERE task_id = ? AND status = 'running' AND worker_id = ? AND lease_token = ? AND lease_until IS NOT NULL AND lease_until > ?",
            values,
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def compute_bridge_prepare(self, task_id, worker_id, payload, now_iso):
        self.conn.execute(
            """INSERT INTO compute_bridge_publications
               (task_id, worker_id, payload, status, last_error, created_at, updated_at)
               VALUES (?, ?, ?, 'prepared', '', ?, ?)
               ON CONFLICT(task_id) DO UPDATE SET
               worker_id=excluded.worker_id, payload=excluded.payload,
               updated_at=excluded.updated_at""",
            (str(task_id), str(worker_id), json.dumps(payload, ensure_ascii=False), now_iso, now_iso),
        )
        self.conn.commit()

    def compute_bridge_publications(self):
        rows = self.conn.execute(
            "SELECT task_id,worker_id,payload,status,last_error,created_at,updated_at "
            "FROM compute_bridge_publications WHERE status IN ('prepared','publish_retry') "
            "ORDER BY created_at,task_id"
        ).fetchall()
        return [{
            "task_id": row[0], "worker_id": row[1], "payload": json.loads(row[2]),
            "status": row[3], "last_error": row[4], "created_at": row[5], "updated_at": row[6]
        } for row in rows]

    def compute_bridge_mark_published(self, task_id, now_iso):
        self.conn.execute(
            "UPDATE compute_bridge_publications SET status='published',last_error='',updated_at=? WHERE task_id=?",
            (now_iso, str(task_id)),
        )
        self.conn.commit()

    def compute_bridge_mark_retry(self, task_id, error, now_iso):
        self.conn.execute(
            "UPDATE compute_bridge_publications SET status='publish_retry',last_error=?,updated_at=? WHERE task_id=?",
            (str(error)[:4000], now_iso, str(task_id)),
        )
        self.conn.commit()

    def compute_bridge_get(self, task_id):
        row = self.conn.execute(
            "SELECT task_id,worker_id,payload,status,last_error,created_at,updated_at "
            "FROM compute_bridge_publications WHERE task_id=?",
            (str(task_id),),
        ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0], "worker_id": row[1], "payload": json.loads(row[2]),
            "status": row[3], "last_error": row[4], "created_at": row[5], "updated_at": row[6]
        }

    def queue_all_rows(self):
        return self.conn.execute("SELECT task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token FROM agent_queue ORDER BY priority DESC, created_at").fetchall()

    def queue_pending_all_rows(self):
        return self.conn.execute("SELECT task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token FROM agent_queue WHERE status IN ('queued', 'running') ORDER BY priority DESC, created_at").fetchall()

    def queue_pending(self, agent=None):
        if agent is None:
            return self.queue_pending_all_rows()
        return self.conn.execute("SELECT task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at, attempts, lease_until, worker_id, last_error, result, lease_token FROM agent_queue WHERE agent = ? AND status IN ('queued', 'running') ORDER BY priority DESC, created_at", (agent,)).fetchall()

    def stats(self):
        return self.conn.execute("SELECT COUNT(*), COALESCE(SUM(synced), 0), COALESCE(SUM(CASE WHEN synced = 0 THEN 1 ELSE 0 END), 0) FROM leads").fetchone()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


if __name__ == "__main__":
    print("Lead database loaded. SQLite persistence is ready.")
