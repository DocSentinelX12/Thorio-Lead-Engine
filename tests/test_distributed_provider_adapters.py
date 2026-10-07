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


def test_llama_cpp_rpc_is_a_separate_substrate_and_never_claims_physical_gpu_proof():
    from lead_engine.llama_cpp_rpc_execution import (
        LlamaCppRpcExecutionConfig,
        LlamaCppRpcExecutionProvider,
    )

    provider = LlamaCppRpcExecutionProvider(
        LlamaCppRpcExecutionConfig(
            binary="llama-cli",
            rpc_endpoints=("127.0.0.1:50052", "127.0.0.1:50053"),
            model="model.gguf",
        ),
        runner=lambda *args, **kwargs: __import__("subprocess").CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        ),
    )
    capabilities = provider.capabilities()
    assert capabilities["distributed_execution_substrate"] is True
    assert capabilities["remote_rpc_execution"] is True
    assert capabilities["multi_node"] is True
    assert capabilities["cuda_execution"] is False
    assert capabilities["nccl_execution"] is False
    assert capabilities["physical_gpu_inventory"] is False
    assert capabilities["physical_identity_attestation"] is False
    command = provider.build_command({"prompt": "hello", "max_tokens": 4})
    assert command[command.index("--rpc") + 1] == "127.0.0.1:50052,127.0.0.1:50053"


def test_llama_cpp_rpc_registration_is_separate_from_api_execution_registry():
    from lead_engine.compute_fabric import ComputeExecutionRegistry
    from lead_engine.llama_cpp_rpc_execution import (
        LlamaCppRpcExecutionConfig,
        LlamaCppRpcExecutionProvider,
    )

    provider = LlamaCppRpcExecutionProvider(
        LlamaCppRpcExecutionConfig(
            binary="llama-cli",
            rpc_endpoints=("127.0.0.1:50052",),
            model="model.gguf",
        ),
        runner=lambda *args, **kwargs: __import__("subprocess").CompletedProcess(
            args=args[0], returncode=0, stdout="ok", stderr=""
        ),
    )
    registry = ComputeExecutionRegistry()
    try:
        registry.register(provider)
    except TypeError:
        pass
    else:
        raise AssertionError("llama.cpp RPC must not enter the API execution registry")


def test_llama_cpp_rpc_rejects_non_loopback_environment_without_explicit_opt_in(monkeypatch):
    from lead_engine.llama_cpp_rpc_execution import LlamaCppRpcExecutionError, LlamaCppRpcExecutionProvider

    monkeypatch.setenv("THORIO_LLAMA_CPP_RPC_ENABLED", "1")
    monkeypatch.setenv("THORIO_LLAMA_CPP_RPC_ENDPOINTS", "10.0.0.2:50052")
    monkeypatch.setenv("THORIO_LLAMA_CPP_RPC_MODEL", "model.gguf")
    monkeypatch.delenv("THORIO_LLAMA_CPP_RPC_ALLOW_INSECURE_NETWORK", raising=False)
    try:
        LlamaCppRpcExecutionProvider.from_environment()
    except LlamaCppRpcExecutionError:
        pass
    else:
        raise AssertionError("non-loopback RPC must require explicit insecure-network opt-in")
