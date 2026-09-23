"""The rack inventory, as SuperRack sends it in NotifyRacksConfigChanged."""

from kite import prolink


def rack(index, name, stereo=False, inp=-1, out=-1):
    return ["[", index, name, 1, 1, 101 if stereo else 100,
            101 if stereo else 100, inp, out, 0, 0, 0, "]"]


def test_reads_index_name_and_input():
    vals = [2] + rack(0, "KICK IN", inp=0) + rack(22, "VOX", stereo=True, inp=30)
    racks = prolink.parse_racks(vals)
    assert [r["index"] for r in racks] == [0, 22]
    assert racks[1]["name"] == "VOX"
    assert racks[1]["stereo"] is True
    assert racks[1]["input"] == 30          # VOX is rack 22 on input 30
    assert racks[0]["stereo"] is False


def test_unassigned_rack_is_marked():
    racks = prolink.parse_racks([1] + rack(40, "SPARE"))
    assert racks[0]["assigned"] is False


def test_empty_means_unnamed_not_unpatched():
    # "Rack 35" is SuperRack's own placeholder name. A rack with a real name is
    # never empty, whatever is patched into it: links follow the rack only.
    named_no_input = prolink.parse_racks([1] + rack(34, "SFIL"))[0]
    placeholder_with_input = prolink.parse_racks([1] + rack(34, "Rack 35", inp=7))[0]
    assert named_no_input["empty"] is False
    assert placeholder_with_input["empty"] is True


def test_ignores_a_truncated_group():
    assert prolink.parse_racks([1, "[", 0, "KICK", "]"]) == []
