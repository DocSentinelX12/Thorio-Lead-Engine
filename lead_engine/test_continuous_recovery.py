from __future__ import annotations
import tempfile
import pytest
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.healing_authorities import HealingAuthorityGateway
from lead_engine.recovery_orchestrator import RecoveryOrchestrator
from lead_engine.continuous_recovery import ContinuousRecoveryController, ContinuousRecoveryError
from lead_engine.physical_fabric import FabricPathState, PhysicalFabricPath

def gateway(db):
    i=ComputeInventory(db_path=db); return HealingAuthorityGateway(inventory=i,recovery_orchestrator=RecoveryOrchestrator(i))

def path(i,p):
    x=PhysicalFabricPath(path_id=p,source_gpu=f"gpu:{p}:a",destination_gpu=f"gpu:{p}:b",segments=(f"gpu:{p}:a",f"rdma:{p}:1"),fabric_domains=(f"domain:{p}",),state=FabricPathState.VERIFIED)
    i.persist_physical_path(x)
    m={"fabric_path_id":p,"measurement_status":"measured","verified":True,"remote_test_server_verified":True,"worker_id":f"worker:{p}","remote_worker_id":f"remote:{p}","remote_endpoint":f"endpoint:{p}","gpu_uuid":f"{p}:a","rdma_device":p,"rdma_port":1,"bandwidth_gbps":100.0}
    i.record_active_gdrdma_measurement(path_id=p,measurement=m,observed_at=1.0); i.record_active_gdrdma_measurement(path_id=p,measurement=m,observed_at=2.0); i.fail_physical_path(p,reason="injected failure",observed_at=10.0)

def evidence(a):
    p=a["path_id"]; return {"physical_evidence":({"segment":f"gpu:{p}:a","result":"pass"},{"segment":f"rdma:{p}:1","result":"pass"}),"active_measurement":{"fabric_path_id":p,"measurement_status":"measured","verified":True,"remote_test_server_verified":True,"worker_id":f"worker:{p}","remote_worker_id":f"remote:{p}","remote_endpoint":f"endpoint:{p}","gpu_uuid":f"{p}:a","rdma_device":p,"rdma_port":1,"bandwidth_gbps":100.0},"observed_at":21.0}

def test_durable_idempotent_episode():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c1"); c.start(generation=1,now=20)
        a=c.observe(path_id="p1",generation=1,fingerprint="fp",criticality=3,confidence=.9,cascade_risk=.1,now=21); b=c.observe(path_id="p1",generation=1,fingerprint="fp",criticality=3,confidence=.9,cascade_risk=.1,now=22)
        assert a["episode_id"]==b["episode_id"] and len(c.snapshot()["episodes"])==1

def test_observation_durably_enqueues_authoritative_recovery_action():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c1"); c.start(generation=1,now=20)
        c.observe(path_id="p1",generation=1,fingerprint="fp",criticality=3,confidence=.9,cascade_risk=.1,now=21)
        actions=g.inventory.active_path_recovery_actions(path_id="p1")
        assert len(actions)==1
        assert actions[0]["generation"]==1
        assert actions[0]["state"]=="PENDING"
        assert actions[0]["path_id"]=="p1"


def test_controller_generation_is_independent_of_path_recovery_generation():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1")
        c1=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c1")
        c1.start(generation=1,now=20)
        c1.observe(path_id="p1",generation=1,fingerprint="fp-1",criticality=2,confidence=.9,cascade_risk=.1,now=21)
        c2=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c2")
        c2.start(generation=2,now=22)
        c2.observe(path_id="p1",generation=2,fingerprint="fp-2",criticality=2,confidence=.9,cascade_risk=.1,now=23)
        result=c2.run_cycle(evidence_provider=evidence,now=23)
        assert result[0]["path_id"]=="p1"
        assert result[0]["state"]=="SUCCEEDED"
        assert result[0]["allow_routing"] is True


def test_stale_controller_is_fenced():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c1=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c1"); c2=ContinuousRecoveryController(gateway=g,db_path=f.name,controller_id="c2")
        c1.start(generation=1,now=1,lease_seconds=10); c2.start(generation=2,now=20,lease_seconds=10)
        with pytest.raises(ContinuousRecoveryError): c1.observe(path_id="p1",generation=1,fingerprint="fp",criticality=2,confidence=.8,cascade_risk=.1,now=21)

def test_independent_episodes_schedule_in_parallel():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); path(g.inventory,"p2"); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=20)
        for p in ("p1","p2"): c.observe(path_id=p,generation=1,fingerprint=p,criticality=2,confidence=.9,cascade_risk=.1,now=21)
        s=c.schedule(now=22); assert len(s)==2 and {x["mode"] for x in s}=={"PARALLEL_INDEPENDENT"}

def test_complete_cycle_closes_after_authoritative_recovery():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=20)
        c.observe(path_id="p1",generation=1,fingerprint="a",criticality=2,confidence=.9,cascade_risk=.1,now=21)
        r=c.run_cycle(evidence_provider=evidence,now=21); assert r[0]["state"]=="SUCCEEDED"; assert c.snapshot()["episodes"][0]["state"]=="RECOVERED"

def test_insufficient_evidence_remains_retryable():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=20)
        c.observe(path_id="p1",generation=1,fingerprint="a",criticality=2,confidence=.9,cascade_risk=.1,now=21)
        r=c.run_cycle(evidence_provider=lambda a:{"physical_evidence":({"segment":f"gpu:{a['path_id']}:a","result":"pass"},),"observed_at":21},now=21)
        assert r[0]["state"]=="RETRY_WAIT" and c.snapshot()["episodes"][0]["state"]=="RETRY_WAIT"

def test_restart_reconciles_durable_unfinished_episode():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        g=gateway(f.name); path(g.inventory,"p1"); c=ContinuousRecoveryController(gateway=g,db_path=f.name); c.start(generation=1,now=20)
        c.observe(path_id="p1",generation=1,fingerprint="a",criticality=2,confidence=.9,cascade_risk=.1,now=21); c.schedule(now=22)
        r=ContinuousRecoveryController(gateway=g,db_path=f.name); r.start(generation=2,now=23); x=r.reconcile(now=24); assert x[0]["state"] in {"RETRY","RETRY_WAIT","REPLAN"}
