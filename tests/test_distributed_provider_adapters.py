from lead_engine.compute_fabric import ComputeExecutionRegistry
from lead_engine.swarmllm_execution import SwarmLLMExecutionConfig, SwarmLLMExecutionProvider
from lead_engine.viiwork_execution import ViiworkExecutionConfig, ViiworkExecutionProvider
from lead_engine.moregpu_execution import MoreGPUExecutionConfig, MoreGPUExecutionProvider

class R:
    def __init__(self,payload): self.status_code=200; self.payload=payload
    def raise_for_status(self): pass
    def json(self): return self.payload
class S:
    def __init__(self): self.calls=[]
    def get(self,url,**kwargs): self.calls.append(("get",url,kwargs)); return R({"data":[]})
    def post(self,url,**kwargs): self.calls.append(("post",url,kwargs)); return R({"ok":True})
def test_distributed_adapters_capability_boundaries():
    for P,C,args,req in [
        (SwarmLLMExecutionProvider,SwarmLLMExecutionConfig,{"base_url":"http://127.0.0.1:8800","api_key":"x"},{"networked_multi_node":True,"community_inference":True}),
        (ViiworkExecutionProvider,ViiworkExecutionConfig,{"base_url":"http://127.0.0.1:8086","mesh_secret":"x"},{"networked_multi_node":True,"community_inference":True}),
        (MoreGPUExecutionProvider,MoreGPUExecutionConfig,{"base_url":"http://127.0.0.1:8787","admin_token":"x"},{"networked_multi_node":True,"api_gpu_execution":True}),
    ]:
        p=P(C(**args),session=S()); c=p.capabilities()
        assert all(c.to_dict()[k] for k in req)
        assert not c.to_dict()["cuda_execution"]
        assert not c.to_dict()["physical_identity_attestation"]
def test_moregpu_is_not_marked_as_openai_inference():
    p=MoreGPUExecutionProvider(MoreGPUExecutionConfig("http://127.0.0.1:8787","x"),session=S())
    assert p.capabilities().community_inference is False
    assert p.capabilities().openai_compatible_api is False
