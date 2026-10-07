"""SwarmLLM community distributed inference adapter.

SwarmLLM exposes an OpenAI-compatible local gateway backed by a peer-to-peer
model-partitioning swarm. It is an inference route, not physical inventory.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse
import requests
from .compute_fabric import ProviderCapabilities

class SwarmLLMExecutionError(RuntimeError): pass

@dataclass(frozen=True)
class SwarmLLMExecutionConfig:
    base_url: str
    api_key: str
    request_timeout_seconds: int = 120
    def __post_init__(self) -> None:
        parsed=urlparse(self.base_url.strip())
        if parsed.scheme not in {"http","https"} or not parsed.netloc: raise ValueError("base_url must be an http or https URL")
        if not self.api_key.strip(): raise ValueError("api_key is required")
        if self.request_timeout_seconds < 1: raise ValueError("request_timeout_seconds must be positive")

class SwarmLLMExecutionProvider:
    provider_id="swarmllm"
    def __init__(self,config:SwarmLLMExecutionConfig,*,session:requests.Session|None=None):
        self.config=config; self._session=session or requests.Session()
    @classmethod
    def from_environment(cls):
        enabled=os.environ.get("THORIO_SWARMLLM_ENABLED","0").strip().lower()
        if enabled not in {"1","true","yes","on"}: raise SwarmLLMExecutionError("THORIO_SWARMLLM_ENABLED must be enabled to register SwarmLLM")
        return cls(SwarmLLMExecutionConfig(os.environ.get("THORIO_SWARMLLM_BASE_URL","http://127.0.0.1:8800").strip(),os.environ.get("SWARMLLM_KEY","").strip(),int(os.environ.get("THORIO_SWARMLLM_REQUEST_TIMEOUT_SECONDS","120"))))
    def capabilities(self)->ProviderCapabilities:
        return ProviderCapabilities(provider_api=True,api_gpu_execution=True,community_inference=True,openai_compatible_api=True,peer_network=True,multi_node=True,networked_multi_node=True,gpu_acquisition=False,cuda_execution=False,nccl_execution=False,physical_identity_attestation=False,arbitrary_process=False)
    def _headers(self): return {"Authorization":f"Bearer {self.config.api_key}","Content-Type":"application/json"}
    def health(self)->Mapping[str,Any]:
        try:
            r=self._session.get(self.config.base_url.rstrip("/")+"/v1/models",headers=self._headers(),timeout=self.config.request_timeout_seconds); r.raise_for_status(); payload=r.json()
        except (requests.RequestException,ValueError) as exc: raise SwarmLLMExecutionError(f"SwarmLLM health check failed: {exc}") from exc
        return {"provider_id":self.provider_id,"state":"available","free_only":True,"capabilities":self.capabilities().to_dict(),"models":payload}
    def execute(self,data:list[Any])->Any:
        if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],Mapping): raise TypeError("SwarmLLM execution requires exactly one OpenAI-compatible request object")
        req=dict(data[0])
        if not str(req.get("model") or "").strip() or not isinstance(req.get("messages"),list) or not req["messages"]: raise ValueError("SwarmLLM request requires model and non-empty messages")
        try:
            r=self._session.post(self.config.base_url.rstrip("/")+"/v1/chat/completions",headers=self._headers(),json=req,timeout=self.config.request_timeout_seconds); r.raise_for_status(); return r.json()
        except (requests.RequestException,ValueError) as exc: raise SwarmLLMExecutionError(f"SwarmLLM execution failed: {exc}") from exc
