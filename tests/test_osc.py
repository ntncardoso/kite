"""OSC on both sides: what goes on the wire and what comes back off it."""

import struct

from kite import prolink
from kite import wing_link as wing


def test_wing_query_has_no_arguments():
    # A query is the address with an empty type tag list; the console answers
    # asynchronously. Anything else would be a write.
    assert wing.osc_build("/ch/1/name") == b"/ch/1/name\x00\x00,\x00\x00\x00"


def test_wing_string_argument_is_padded_to_four_bytes():
    msg = wing.osc_build("/ch/1/name", [("s", "KICK")])
    assert msg.endswith(b"KICK\x00\x00\x00\x00")
    assert len(msg) % 4 == 0


def test_wing_parses_multi_tag_reply():
    # Faders answer ",sff" and the useful value is the last numeric one.
    blob = wing.osc_pad("/ch/1/fdr") + wing.osc_pad(",sff") + wing.osc_pad("-oo") \
        + struct.pack(">f", 0.0) + struct.pack(">f", -144.0)
    addr, vals = wing.osc_parse(blob)
    assert addr == "/ch/1/fdr"
    assert vals[0] == "-oo"
    assert wing.last_numeric(vals) == -144.0


def test_wing_parse_survives_rubbish():
    assert wing.osc_parse(b"\x01\x02\x03") in ((None, []), ("\x01\x02\x03", []))


def test_prolink_round_trip():
    payload = struct.pack(">i", 7) + struct.pack(">i", 22)
    blob = prolink.osc_build("/waves.com/remote/ShowRackByID", "ii", payload)
    addr, tags, vals = prolink.osc_decode(blob)
    assert addr == "/waves.com/remote/ShowRackByID"
    assert tags == ",ii"
    assert vals == [7, 22]


def test_prolink_decode_never_raises():
    addr, tags, vals = prolink.osc_decode(b"/x\x00\x00,i\x00\x00")   # tag with no value
    assert addr == "<undecodable>" or vals == []


def test_prolink_decodes_booleans_and_strings():
    blob = prolink.osc_build("/waves.com/remote/GiveRackName", "isT",
                             struct.pack(">i", 3) + prolink._pad("VOX"))
    _, _, vals = prolink.osc_decode(blob)
    assert vals == [3, "VOX", True]
