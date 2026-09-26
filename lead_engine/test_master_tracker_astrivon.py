from lead_engine.master_tracker_sync import _routes


def test_astrivon_is_an_independent_master_tracker_route():
    assert _routes({"potential_routes": ["Astrivon Labs"]}) == ["Astrivon Labs"]


def test_all_four_routes_are_preserved_in_master_tracker_routing():
    assert set(_routes({"potential_routes": ["Shiftr", "Paxus", "Thorio", "Astrivon Labs"]})) == {"Shiftr", "Paxus", "Thorio", "Astrivon Labs"}
