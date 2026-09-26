"""Durable evidence-governed self-optimizing GPU-fabric control plane."""
from __future__ import annotations
import hashlib, json, math, sqlite3, time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

RISK={"route":1,"placement":2,"migration":3,"recovery":3,"experiment":2}
@dataclass(frozen=True)
class Evidence:
    evidence_id:str; source:str; kind:str; subject:str; observed_at:float; payload:dict[str,Any]; confidence:float; provenance:str
@dataclass(frozen=True)
class ActionDecision:
    decision_id:str; action:str; risk_level:int; authorized:bool; confidence:float; independent_source_count:int; required_source_count:int; evidence_ids:tuple[str,...]; reason:str
@dataclass(frozen=True)
class StrategyDecision:
    strategy_id:str; capability:str; role:str; eligible:bool; reason:str

class UnifiedControlPlane:
    """Coordinates intelligence without becoming an authority for physical truth."""
    MIN_SAMPLES=20; Z=1.96
    def __init__(self,db_path=":memory:"):
        self.db_path=db_path; self._mem=sqlite3.connect(":memory:") if db_path==":memory:" else None
        if self._mem:self._mem.row_factory=sqlite3.Row
        self._init()
    def _db(self):
        if self._mem:return self._mem
        c=sqlite3.connect(self.db_path,timeout=30); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._db() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS evidence(eid TEXT PRIMARY KEY,source TEXT,kind TEXT,subject TEXT,observed REAL,payload TEXT,confidence REAL,provenance TEXT,recorded REAL);
CREATE TABLE IF NOT EXISTS decisions(did TEXT PRIMARY KEY,action TEXT,risk INTEGER,authorized INTEGER,confidence REAL,sources INTEGER,required INTEGER,eids TEXT,reason TEXT,created REAL);
CREATE TABLE IF NOT EXISTS capabilities(name TEXT PRIMARY KEY,incumbent TEXT,fallback TEXT,min_avail REAL,min_rel REAL,updated REAL);
CREATE TABLE IF NOT EXISTS strategies(sid TEXT PRIMARY KEY,capability TEXT,role TEXT,status TEXT,availability REAL,metadata TEXT,created REAL,promoted REAL);
CREATE TABLE IF NOT EXISTS observations(oid TEXT PRIMARY KEY,sid TEXT,success INTEGER,performance REAL,safety INTEGER,observed REAL,eids TEXT,metadata TEXT);
CREATE TABLE IF NOT EXISTS outcomes(oid TEXT PRIMARY KEY,did TEXT,sid TEXT,outcome TEXT,observed REAL,metrics TEXT,eids TEXT,recorded REAL);
CREATE TABLE IF NOT EXISTS counterfactuals(cid TEXT PRIMARY KEY,did TEXT,sid TEXT,expected TEXT,confidence REAL,eids TEXT,created REAL);''')
    @staticmethod
    def _id(prefix,payload):
        return prefix+":"+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    @staticmethod
    def _clamp(v):
        try:v=float(v)
        except (TypeError,ValueError):return 0.0
        return max(0.0,min(1.0,v)) if math.isfinite(v) else 0.0
    def record_evidence(self,*,source,kind,subject,observed_at,payload,confidence=1.0,provenance=""):
        if not source.strip() or not kind.strip() or not subject.strip():raise ValueError("source, kind, and subject are required")
        c=self._clamp(confidence); p={"source":source,"kind":kind,"subject":subject,"observed":float(observed_at),"payload":dict(payload),"confidence":c,"provenance":provenance}; eid=self._id("evidence",p)
        e=Evidence(eid,source,kind,subject,float(observed_at),dict(payload),c,provenance)
        with self._db() as d:d.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?,?,?)",(eid,source,kind,subject,float(observed_at),json.dumps(dict(payload),sort_keys=True),c,provenance,time.time()))
        return e
    def evidence_for(self,subject,*,since=None):
        q="SELECT * FROM evidence WHERE subject=?"; a=[subject]
        if since is not None:q+=" AND observed>=?";a.append(float(since))
        q+=" ORDER BY observed,eid"
        with self._db() as d:r=d.execute(q,a).fetchall()
        return tuple(Evidence(x["eid"],x["source"],x["kind"],x["subject"],x["observed"],json.loads(x["payload"]),x["confidence"],x["provenance"]) for x in r)
    @staticmethod
    def required_sources(*,action,workload_criticality=1,redundancy=1):
        return min(5,max(2,RISK.get(action,3)+max(1,min(3,int(workload_criticality)))-1+max(1,min(3,int(redundancy)))-1))
    def authorize(self,*,action,subject,evidence=None,workload_criticality=1,redundancy=1,confidence_floor=.70,safety_ok=True,fallback_available=True,now=None):
        es=tuple(evidence if evidence is not None else self.evidence_for(subject)); sources=tuple(sorted({e.source for e in es if e.confidence>0 and e.provenance.strip()})); req=self.required_sources(action=action,workload_criticality=workload_criticality,redundancy=redundancy); conf=min((e.confidence for e in es),default=0.0); ok=bool(safety_ok and fallback_available and len(sources)>=req and conf>=confidence_floor)
        reason="adaptive evidence threshold satisfied" if ok else ("hard safety floor failed" if not safety_ok else "continuous proven fallback is unavailable" if not fallback_available else f"insufficient independent evidence: {len(sources)}/{req} sources" if len(sources)<req else f"confidence below floor: {conf:.3f}<{confidence_floor:.3f}")
        p={"action":action,"subject":subject,"risk":RISK.get(action,3),"ok":ok,"conf":conf,"sources":sources,"required":req,"eids":[e.evidence_id for e in es],"reason":reason};did=self._id("decision",p)
        with self._db() as d:d.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?)",(did,action,RISK.get(action,3),int(ok),conf,len(sources),req,json.dumps([e.evidence_id for e in es]),reason,time.time() if now is None else float(now)))
        return ActionDecision(did,action,RISK.get(action,3),ok,conf,len(sources),req,tuple(e.evidence_id for e in es),reason)
    def register_capability(self,*,capability,incumbent_strategy_id,fallback_strategy_id,minimum_availability=.999,minimum_reliability=.999):
        if not capability.strip():raise ValueError("capability is required")
        with self._db() as d:d.execute("INSERT INTO capabilities VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET incumbent=excluded.incumbent,fallback=excluded.fallback,min_avail=excluded.min_avail,min_rel=excluded.min_rel,updated=excluded.updated",(capability,incumbent_strategy_id,fallback_strategy_id,self._clamp(minimum_availability),self._clamp(minimum_reliability),time.time()))
    def register_strategy(self,*,strategy_id,capability,role="challenger",metadata=None):
        if role not in {"champion","challenger","fallback"}:raise ValueError("unsupported strategy role")
        with self._db() as d:
            if d.execute("SELECT 1 FROM capabilities WHERE name=?",(capability,)).fetchone() is None:raise ValueError("capability must be registered before strategy")
            if d.execute("SELECT 1 FROM strategies WHERE sid=?",(strategy_id,)).fetchone() is not None:raise ValueError("strategy already exists")
            d.execute("INSERT INTO strategies VALUES(?,?,?,?,?,?,?,?)",(strategy_id,capability,role,"active",1.0,json.dumps(dict(metadata or {}),sort_keys=True),time.time(),None))
        return StrategyDecision(strategy_id,capability,role,True,"registered without replacing incumbent")
    def set_strategy_availability(self,*,strategy_id,availability):
        with self._db() as d:
            if d.execute("SELECT 1 FROM strategies WHERE sid=?",(strategy_id,)).fetchone() is None:raise ValueError("unknown strategy")
            d.execute("UPDATE strategies SET availability=? WHERE sid=?",(self._clamp(availability),strategy_id))
    def observe_strategy(self,*,strategy_id,success,performance,safety_ok,observed_at,evidence,metadata=None):
        with self._db() as d:
            row=d.execute("SELECT capability FROM strategies WHERE sid=?",(strategy_id,)).fetchone()
            if row is None:raise ValueError("unknown strategy")
            p={"sid":strategy_id,"success":bool(success),"performance":performance,"observed":observed_at,"eids":[e.evidence_id for e in evidence]};oid=self._id("observation",p)
            d.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?)",(oid,strategy_id,int(success),performance,int(safety_ok),float(observed_at),json.dumps([e.evidence_id for e in evidence]),json.dumps(dict(metadata or {}),sort_keys=True)))
    @staticmethod
    def _ci(values):
        n=len(values);m=sum(values)/n
        if n<2:return m,float("inf")
        var=sum((x-m)**2 for x in values)/(n-1);return m,1.96*math.sqrt(var/n)
    def strategy_decision(self,*,strategy_id,window=20):
        with self._db() as d:
            s=d.execute("SELECT * FROM strategies WHERE sid=?",(strategy_id,)).fetchone()
            if s is None:raise ValueError("unknown strategy")
            cap=d.execute("SELECT * FROM capabilities WHERE name=?",(s["capability"],)).fetchone(); incumbent=cap["incumbent"] if cap else None
            rows=d.execute("SELECT * FROM observations WHERE sid=? ORDER BY observed DESC LIMIT ?",(strategy_id,window)).fetchall()
            if not rows:return StrategyDecision(strategy_id,s["capability"],s["role"],False,"no outcome evidence")
            reliability=sum(r["success"] for r in rows)/len(rows);safety=all(bool(r["safety"]) for r in rows)
            if strategy_id==incumbent or s["role"]=="champion":return StrategyDecision(strategy_id,s["capability"],s["role"],safety and reliability>=(cap["min_rel"] if cap else .999),"incumbent remains protected")
            if len(rows)<self.MIN_SAMPLES:return StrategyDecision(strategy_id,s["capability"],s["role"],False,f"insufficient sustained evidence: {len(rows)}/{self.MIN_SAMPLES} observations")
            ir=d.execute("SELECT * FROM observations WHERE sid=? ORDER BY observed DESC LIMIT ?",(incumbent,window)).fetchall() if incumbent else []
            if len(ir)<self.MIN_SAMPLES:return StrategyDecision(strategy_id,s["capability"],s["role"],False,"incumbent has no comparable outcome window")
            cp=[float(r["performance"]) for r in rows if r["performance"] is not None];ip=[float(r["performance"]) for r in ir if r["performance"] is not None]
            if len(cp)<self.MIN_SAMPLES or len(ip)<self.MIN_SAMPLES:return StrategyDecision(strategy_id,s["capability"],s["role"],False,"insufficient comparable performance observations")
            cm,ce=self._ci(cp);im,ie=self._ci(ip);direction=str(json.loads(s["metadata"] or "{}").get("optimization_direction","max")).lower()
            better=cm-ce>im+ie if direction=="max" else cm+ce<im-ie
            eligible=safety and reliability>=(cap["min_rel"] if cap else .999) and s["availability"]>=(cap["min_avail"] if cap else .999) and better
            return StrategyDecision(strategy_id,s["capability"],s["role"],eligible,"sustained statistically separated superiority with safety and availability floors" if eligible else "challenger has not proven sustained superiority while preserving hard floors")
    def promote(self,*,strategy_id):
        decision=self.strategy_decision(strategy_id=strategy_id)
        if not decision.eligible:return decision
        with self._db() as d:
            row=d.execute("SELECT capability FROM strategies WHERE sid=?",(strategy_id,)).fetchone();cap=d.execute("SELECT * FROM capabilities WHERE name=?",(row["capability"],)).fetchone();inc=cap["incumbent"] if cap else None
            if not inc:return StrategyDecision(strategy_id,row["capability"],"challenger",False,"no protected incumbent")
            d.execute("UPDATE strategies SET role='fallback',status='active',promoted=COALESCE(promoted,?) WHERE sid=?",(time.time(),inc));d.execute("UPDATE strategies SET role='champion',status='active',promoted=? WHERE sid=?",(time.time(),strategy_id));d.execute("UPDATE capabilities SET incumbent=?,fallback=?,updated=? WHERE name=?",(strategy_id,inc,time.time(),row["capability"]))
        return StrategyDecision(strategy_id,row["capability"],"champion",True,"promoted while proven incumbent remains continuously available as fallback")
    def record_counterfactual(self,*,decision_id,strategy_id,expected_outcome,confidence,evidence):
        p={"did":decision_id,"sid":strategy_id,"expected":dict(expected_outcome),"confidence":confidence,"eids":[e.evidence_id for e in evidence]};cid=self._id("counterfactual",p)
        with self._db() as d:d.execute("INSERT OR IGNORE INTO counterfactuals VALUES(?,?,?,?,?,?,?)",(cid,decision_id,strategy_id,json.dumps(dict(expected_outcome),sort_keys=True),self._clamp(confidence),json.dumps([e.evidence_id for e in evidence]),time.time()))
        return cid
    def record_outcome(self,*,decision_id,outcome,observed_at,metrics,evidence,strategy_id=None):
        if outcome not in {"success","failure","partial","rolled_back"}:raise ValueError("unsupported outcome")
        p={"did":decision_id,"sid":strategy_id,"outcome":outcome,"observed":observed_at,"metrics":dict(metrics),"eids":[e.evidence_id for e in evidence]};oid=self._id("outcome",p)
        with self._db() as d:d.execute("INSERT OR IGNORE INTO outcomes VALUES(?,?,?,?,?,?,?,?)",(oid,decision_id,strategy_id,outcome,float(observed_at),json.dumps(dict(metrics),sort_keys=True),json.dumps([e.evidence_id for e in evidence]),time.time()))
        return oid
    def capability_state(self,capability):
        with self._db() as d:
            c=d.execute("SELECT * FROM capabilities WHERE name=?",(capability,)).fetchone()
            if c is None:return None
            i=d.execute("SELECT * FROM strategies WHERE sid=?",(c["incumbent"],)).fetchone() if c["incumbent"] else None;f=d.execute("SELECT * FROM strategies WHERE sid=?",(c["fallback"],)).fetchone() if c["fallback"] else None
        return {"capability":capability,"incumbent_strategy_id":c["incumbent"],"fallback_strategy_id":c["fallback"],"incumbent_available":bool(i and i["status"]=="active" and i["availability"]>=c["min_avail"]),"fallback_available":bool(f and f["status"]=="active" and f["availability"]>=c["min_avail"]),"minimum_availability":c["min_avail"],"minimum_reliability":c["min_rel"]}
