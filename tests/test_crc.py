"""CRC-16/CCITT-FALSE conformance tests."""

from donglora.crc import crc16


def test_check_value_matches_spec():
    # PROTOCOL.md §2.2 / Appendix B.
    assert crc16(b"123456789") == 0x29B1


def test_empty_input_is_initial_value():
    # No reflection, no XOR-out: empty leaves init untouched.
    assert crc16(b"") == 0xFFFF


def test_single_null_byte():
    # A naive init=0 impl would yield 0; correct init=0xFFFF yields 0xE1F0.
    assert crc16(b"\x00") == 0xE1F0


def test_differs_from_kermit_variant():
    # CRC-16/KERMIT of "123456789" is 0x2189.
    assert crc16(b"123456789") != 0x2189
