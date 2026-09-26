"""Continuous autonomous recovery controller for the GPU fabric."""
from __future__ import annotations
import hashlib, json, sqlite3, time
from typing import Any, Callable, Mapping
from .healing_authorities import HealingAuthorityGateway

class ContinuousRecoveryError(RuntimeError): pass

class RecoveryEpisodeStore:
    def __init__(self, db_path=":memory:"):
        self.db_path=db_path; self._memory=sqlite3.connect(":memory:") if db_path==":memory:" else None
        if self._memory: self._memory.row_factory=sqlite3.Row
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recovery_episodes(
              episode_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, generation INTEGER NOT NULL,
              fingerprint TEXT NOT NULL, state TEXT NOT NULL, criticality INTEGER NOT NULL,
              confidence REAL NOT NULL, cascade_risk REAL NOT NULL, failure_domains_json TEXT NOT NULL,
              affected_entities_json TEXT NOT NULL, strategy TEXT NOT NULL, mode TEXT,
              last_error TEXT, owner TEXT, fencing_token INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL, updated_at REAL NOT NULL,
              UNIQUE(scope_id,generation,fingerprint));
            CREATE TABLE IF NOT EXISTS recovery_episode_events(
              event_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, kind TEXT NOT NULL,
              payload_json TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_controller_leases(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), controller_id TEXT NOT NULL,
              generation INTEGER NOT NULL, fencing_token INTEGER NOT NULL,
              lease_expires_at REAL NOT NULL, state TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_recovery_episodes_state ON recovery_episodes(state,updated_at);
            """)
            if not db.execute("SELECT 1 FROM recovery_controller_leases WHERE singleton=1").fetchone():
                db.execute("INSERT INTO recovery_controller_leases VALUES(1,'',0,0,0,'EMPTY')")
    def _connect(self):
        if self._memory: return self._memory
        db=sqlite3.connect(self.db_path,timeout=30); db.row_factory=sqlite3.Row; return db
    @staticmethod
    def _id(scope,generation,fingerprint):
        return "episode:"+hashlib.sha256(f"{scope}\0{generation}\0{fingerprint}".encode()).hexdigest()
    def acquire_controller(self,*,controller_id,generation,now=None,lease_seconds=300):
        if not controller_id.strip() or generation<1 or lease_seconds<=0: raise ValueError("invalid controller lease")
        now=time.time() if now is None else float(now)
        with self._connect() as db:
            row=db.execute("SELECT * FROM recovery_controller_leases WHERE singleton=1").fetchone()
            if row["controller_id"] not in {"",controller_id} and float(row["lease_expires_at"])>now:
                raise ContinuousRecoveryError("continuous recovery controller lease is held")
            token=int(row["fencing_token"])+(row["controller_id"]!=controller_id or int(row["generation"])!=generation)
            db.execute("UPDATE recovery_controller_leases SET controller_id=?,generation=?,fencing_token=?,lease_expires_at=?,state='ACTIVE' WHERE singleton=1",(controller_id,generation,token,now+lease_seconds))
            return dict(db.execute("SELECT * FROM recovery_controller_leases WHERE singleton=1").fetchone())
    def lease(self):
        with self._connect() as db: return dict(db.execute("SELECT * FROM recovery_controller_leases WHERE singleton=1").fetchone())
    def assert_controller(self,*,controller_id,generation,fencing_token,now=None):
        now=time.time() if now is None else float(now); r=self.lease()
        if r["controller_id"]!=controller_id or int(r["generation"])!=generation or int(r["fencing_token"])!=fencing_token or r["state"]!="ACTIVE" or float(r["lease_expires_at"])<=now:
            raise ContinuousRecoveryError("controller is stale, fenced, or lease expired")
    def _episode(self,db,eid):
        r=db.execute("SELECT * FROM recovery_episodes WHERE episode_id=?",(eid,)).fetchone()
        if r is None: raise ContinuousRecoveryError("unknown recovery episode")
        x=dict(r); x["failure_domains"]=tuple(json.loads(x.pop("failure_domains_json"))); x["affected_entities"]=tuple(tuple(v) for v in json.loads(x.pop("affected_entities_json"))); return x
    def upsert_episode(self,*,scope_id,generation,fingerprint,criticality,confidence,cascade_risk,failure_domains,affected_entities,strategy,now=None):
        if not scope_id.strip() or not fingerprint.strip() or generation<1: raise ValueError("invalid episode identity")
        if criticality not in (1,2,3) or not 0<=confidence<=1 or not 0<=cascade_risk<=1: raise ValueError("invalid episode risk")
        now=time.time() if now is None else float(now); eid=self._id(scope_id,generation,fingerprint)
        with self._connect() as db:
            if db.execute("SELECT 1 FROM recovery_episodes WHERE episode_id=?",(eid,)).fetchone() is None:
                db.execute("""INSERT INTO recovery_episodes(episode_id,scope_id,generation,fingerprint,state,criticality,confidence,cascade_risk,failure_domains_json,affected_entities_json,strategy,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid,scope_id,generation,fingerprint,"OBSERVED",criticality,float(confidence),float(cascade_risk),json.dumps(list(failure_domains)),json.dumps([list(v) for v in affected_entities]),strategy,now,now))
                db.execute("INSERT OR IGNORE INTO recovery_episode_events VALUES(?,?,?,?,?)",(hashlib.sha256(f"{eid}\0observed".encode()).hexdigest(),eid,"observed",json.dumps({"generation":generation,"strategy":strategy}),now))
            else: db.execute("UPDATE recovery_episodes SET updated_at=? WHERE episode_id=?",(now,eid))
            return self._episode(db,eid)
    def update(self,*,episode_id,state,now=None,owner=None,fencing_token=None,mode=None,error=None,payload=None):
        now=time.time() if now is None else float(now)
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM recovery_episodes WHERE episode_id=?",(episode_id,)).fetchone(): raise ContinuousRecoveryError("unknown recovery episode")
            db.execute("UPDATE recovery_episodes SET state=?,updated_at=?,owner=COALESCE(?,owner),fencing_token=COALESCE(?,fencing_token),mode=COALESCE(?,mode),last_error=? WHERE episode_id=?",(state,now,owner,fencing_token,mode,error,episode_id))
            raw=json.dumps(dict(payload or {}),sort_keys=True,default=str); eid=hashlib.sha256(f"{episode_id}\0{state}\0{raw}".encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO recovery_episode_events VALUES(?,?,?,?,?)",(eid,episode_id,state.lower(),raw,now))
            return self._episode(db,episode_id)
    def episodes(self,*,states=None):
        with self._connect() as db:
            if states:
                q="SELECT episode_id FROM recovery_episodes WHERE state IN ("+(",".join("?" for _ in states))+") ORDER BY created_at,episode_id"; rows=db.execute(q,states).fetchall()
            else: rows=db.execute("SELECT episode_id FROM recovery_episodes ORDER BY created_at,episode_id").fetchall()
            return tuple(self._episode(db,r["episode_id"]) for r in rows)
    def snapshot(self): return {"lease":self.lease(),"episodes":self.episodes()}

class ContinuousRecoveryController:
    def __init__(self,*,gateway:HealingAuthorityGateway,db_path=":memory:",controller_id="healing-controller"):
        self.gateway=gateway; self.store=RecoveryEpisodeStore(db_path); self.controller_id=controller_id; self._lease=None
    def start(self,*,generation,now=None,lease_seconds=300):
        self._lease=self.store.acquire_controller(controller_id=self.controller_id,generation=generation,now=now,lease_seconds=lease_seconds); return dict(self._lease)
    def _assert(self,now=None):
        if self._lease is None: self._lease=self.store.lease()
        self.store.assert_controller(controller_id=self.controller_id,generation=int(self._lease["generation"]),fencing_token=int(self._lease["fencing_token"]),now=now); return self._lease
    def observe(self,*,path_id,generation,fingerprint,criticality,confidence,cascade_risk,strategy="known_good_recovery",now=None):
        self._assert(now); evidence=self.gateway.path(path_id); impact=self.gateway.dependencies.impact(path_id); prediction=self.gateway.intelligence.predictor.predict(scope_id=path_id, observed_at=now); exact=str(evidence["path_id"])
        if exact!=str(path_id).strip(): raise ContinuousRecoveryError("authoritative path identity changed")
        episode = self.store.upsert_episode(
            scope_id=exact,
            generation=generation,
            fingerprint=fingerprint,
            criticality=criticality,
            confidence=confidence,
            cascade_risk=cascade_risk,
            failure_domains=tuple(impact["failure_domains"]),
            affected_entities=tuple(tuple(x) for x in impact["affected_entities"]),
            strategy=strategy,
            now=now,
        )
        durable_actions = self.gateway.recovery_orchestrator.discover(now=now)
        matching_actions = tuple(
            action for action in durable_actions if str(action["path_id"]) == exact
        )
        if not matching_actions:
            raise ContinuousRecoveryError(
                "authoritative recovery action was not durably enqueued for observed path"
            )
        return self.store.update(
            episode_id=episode["episode_id"],
            state="OBSERVED",
            now=now,
            payload={
                "prediction": prediction,
                "recovery_action_id": matching_actions[-1]["action_id"],
                "recovery_action_generation": matching_actions[-1]["generation"],
            },
        )

