from lead_engine.nccl_execution_adapter import NCCLExecutionAdapter


def test_nccl_command_contains_only_explicit_launch_environment():
    adapter = NCCLExecutionAdapter()
    spec = type("Spec", (), {"world_size": 2, "master_addr": "10.0.0.1", "master_port": 29500, "socket_ifname": "eth0"})()
    command = adapter.build_command(spec, executable="python", arguments=("worker.py",))
    assert command.argv == ("python", "worker.py")
    assert dict(command.environment)["WORLD_SIZE"] == "2"


def test_nccl_observation_parser_ignores_unobserved_lines():
    raw = "noise\n{\"evidence_type\":\"other\"}\n" + "{\"evidence_type\":\"nccl_physical_execution\",\"rank\":0}\n"
    records = NCCLExecutionAdapter.parse_observed_records(raw)
    assert len(records) == 1
    assert records[0]["rank"] == 0
