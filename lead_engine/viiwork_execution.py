"""viiwork mesh inference adapter.

viiwork turns llama.cpp, vLLM and FreeToken nodes into one OpenAI-compatible
fleet. The adapter consumes that gateway and keeps mesh resources outside
physical inventory.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse
import requests
from .compute_fabric import ProviderCapabilities

class ViiworkExecutionError(RuntimeError): pass
@dataclass(frozen=True)
class ViiworkExecutionConfig:
    base_url:str
    mesh_secret:str
    request_timeout_seconds:int=120
    def __post_init__(self):
        p=urlparse(self.base_url.strip())
        if p.scheme not in {"http","https"} or not p.netloc: raise ValueError("base_url must be an http or https URL")
        if not self.mesh_secret.strip(): raise ValueError("mesh_secret is required")
        if self.request_timeout_seconds<1: raise ValueError("request_timeout_seconds must be positive")
class ViiworkExecutionProvider:
    provider_id="viiwork"
    def __init__(self,config,*,session=None): self.config=config; self._session=session or requests.Session()
    @classmethod
    def from_environment(cls):
        enabled=os.environ.get("THORIO_VIIWORK_ENABLED","0").strip().lower()
        if enabled not in {"1","true","yes","on"}: raise ViiworkExecutionError("THORIO_VIIWORK_ENABLED must be enabled to register viiwork")
        return cls(ViiworkExecutionConfig(os.environ.get("THORIO_VIIWORK_BASE_URL","http://127.0.0.1:8086").strip(),os.environ.get("VIIWORK_MESH_SECRET","").strip(),int(os.environ.get("THORIO_VIIWORK_REQUEST_TIMEOUT_SECONDS","120"))))
    def capabilities(self):
        return ProviderCapabilities(provider_api=True,api_gpu_execution=True,community_inference=True,openai_compatible_api=True,peer_network=True,multi_node=True,networked_multi_node=True,gpu_acquisition=False,cuda_execution=False,nccl_execution=False,physical_identity_attestation=False,arbitrary_process=False)
    def _headers(self): return {"Authorization":f"Bearer {self.config.mesh_secret}","Content-Type":"application/json"}
    def health(self):
        try:
            r=self._session.get(self.config.base_url.rstrip("/")+"/v1/models",headers=self._headers(),timeout=self.config.request_timeout_seconds); r.raise_for_status(); payload=r.json()
        except (requests.RequestException,ValueError) as exc: raise ViiworkExecutionError(f"viiwork health check failed: {exc}") from exc
        return {"provider_id":self.provider_id,"state":"available","free_only":True,"capabilities":self.capabilities().to_dict(),"models":payload}
    def execute(self,data):
        if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],Mapping): raise TypeError("viiwork execution requires exactly one OpenAI-compatible request object")
        req=dict(data[0])
        if not str(req.get("model") or "").strip() or not isinstance(req.get("messages"),list) or not req["messages"]: raise ValueError("viiwork request requires model and non-empty messages")
        try:
            r=self._session.post(self.config.base_url.rstrip("/")+"/v1/chat/completions",headers=self._headers(),json=req,timeout=self.config.request_timeout_seconds); r.raise_for_status(); return r.json()
        except (requests.RequestException,ValueError) as exc: raise ViiworkExecutionError(f"viiwork execution failed: {exc}") from exc
