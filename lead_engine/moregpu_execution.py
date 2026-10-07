"""MoreGPU native compute-pool adapter.

MoreGPU is a coordinator/worker compute pool rather than an OpenAI gateway.
This adapter accepts the documented benchmark/data job contract and never
promotes the pool into Thorio's physical inventory.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse
import requests
from .compute_fabric import ProviderCapabilities
class MoreGPUExecutionError(RuntimeError): pass
@dataclass(frozen=True)
class MoreGPUExecutionConfig:
    base_url:str
    admin_token:str
    request_timeout_seconds:int=120
    def __post_init__(self):
        p=urlparse(self.base_url.strip())
        if p.scheme not in {"http","https"} or not p.netloc: raise ValueError("base_url must be an http or https URL")
        if not self.admin_token.strip(): raise ValueError("admin_token is required")
        if self.request_timeout_seconds<1: raise ValueError("request_timeout_seconds must be positive")
class MoreGPUExecutionProvider:
    provider_id="moregpu"
    def __init__(self,config,*,session=None): self.config=config; self._session=session or requests.Session()
    @classmethod
    def from_environment(cls):
        enabled=os.environ.get("THORIO_MOREGPU_ENABLED","0").strip().lower()
        if enabled not in {"1","true","yes","on"}: raise MoreGPUExecutionError("THORIO_MOREGPU_ENABLED must be enabled to register MoreGPU")
        return cls(MoreGPUExecutionConfig(os.environ.get("THORIO_MOREGPU_BASE_URL","http://127.0.0.1:8787").strip(),os.environ.get("MOREGPU_ADMIN_TOKEN","").strip(),int(os.environ.get("THORIO_MOREGPU_REQUEST_TIMEOUT_SECONDS","120"))))
    def capabilities(self):
        return ProviderCapabilities(provider_api=True,api_gpu_execution=True,community_inference=False,openai_compatible_api=False,peer_network=True,multi_node=True,networked_multi_node=True,gpu_acquisition=False,cuda_execution=False,nccl_execution=False,physical_identity_attestation=False,arbitrary_process=False)
    def _headers(self): return {"Authorization":f"Bearer {self.config.admin_token}","Content-Type":"application/json"}
    def health(self):
        try:
            r=self._session.get(self.config.base_url.rstrip("/")+"/device",headers=self._headers(),timeout=self.config.request_timeout_seconds); r.raise_for_status(); payload=r.json()
        except (requests.RequestException,ValueError) as exc: raise MoreGPUExecutionError(f"MoreGPU device check failed: {exc}") from exc
        return {"provider_id":self.provider_id,"state":"available","free_only":True,"capabilities":self.capabilities().to_dict(),"device":payload}
    def execute(self,data):
        if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],Mapping): raise TypeError("MoreGPU execution requires one job object")
        job=dict(data[0])
        if not str(job.get("kernel") or "").strip(): raise ValueError("MoreGPU job requires kernel")
        try:
            r=self._session.post(self.config.base_url.rstrip("/")+"/submit",headers=self._headers(),json=job,timeout=self.config.request_timeout_seconds); r.raise_for_status(); return r.json()
        except (requests.RequestException,ValueError) as exc: raise MoreGPUExecutionError(f"MoreGPU submission failed: {exc}") from exc
