import unittest

from src.blackroot_consensus import sha256d
from src.blackroot_p2p import (
    DEFAULT_MAX_PAYLOAD,
    HEADER_SIZE,
    MessageStreamParser,
    decode_message,
    encode_message,
)


MAGIC = bytes.fromhex("b2a1c3d4")


class MessageFramingTests(unittest.TestCase):
    def test_round_trip_empty_and_binary_payloads(self):
        for payload in (b"", b"\x00\xffhello"):
            frame = encode_message(MAGIC, "version", payload)
            self.assertEqual(decode_message(frame, MAGIC), ("version", payload))
            self.assertEqual(len(frame), HEADER_SIZE + len(payload))

    def test_incremental_parser_handles_fragmentation(self):
        frame = encode_message(MAGIC, "ping", b"12345678")
        parser = MessageStreamParser(MAGIC)
        self.assertEqual(parser.feed(frame[:7]), [])
        self.assertEqual(parser.buffered_bytes, 7)
        self.assertEqual(parser.feed(frame[7:19]), [])
        self.assertEqual(parser.feed(frame[19:]), [("ping", b"12345678")])
        self.assertEqual(parser.buffered_bytes, 0)

    def test_incremental_parser_handles_multiple_messages(self):
        parser = MessageStreamParser(MAGIC)
        frames = encode_message(MAGIC, "ping", b"a") + encode_message(MAGIC, "pong", b"b")
        self.assertEqual(parser.feed(frames), [("ping", b"a"), ("pong", b"b")])

    def test_parser_accepts_many_frames_larger_than_single_frame_bound(self):
        parser = MessageStreamParser(MAGIC, max_payload=8)
        frames = (
            encode_message(MAGIC, "ping", b"12345678", max_payload=8)
            + encode_message(MAGIC, "pong", b"abcdefgh", max_payload=8)
            + encode_message(MAGIC, "ack", b"ok", max_payload=8)
        )
        self.assertEqual(
            parser.feed(frames),
            [("ping", b"12345678"), ("pong", b"abcdefgh"), ("ack", b"ok")],
        )
        self.assertEqual(parser.buffered_bytes, 0)

    def test_rejects_wrong_magic(self):
        frame = encode_message(MAGIC, "ping", b"x")
        with self.assertRaisesRegex(ValueError, "magic mismatch"):
            decode_message(frame, b"bad!")
        parser = MessageStreamParser(MAGIC)
        with self.assertRaisesRegex(ValueError, "magic mismatch"):
            parser.feed(b"nope" + bytes(30))

    def test_rejects_bad_checksum(self):
        frame = bytearray(encode_message(MAGIC, "ping", b"payload"))
        frame[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            decode_message(bytes(frame), MAGIC)

    def test_rejects_oversized_payload_before_waiting_for_body(self):
        frame = MAGIC + b"ping" + bytes(8) + (9).to_bytes(4, "little") + bytes(4)
        with self.assertRaisesRegex(ValueError, "exceeds configured limit"):
            decode_message(frame, MAGIC, max_payload=8)
        parser = MessageStreamParser(MAGIC, max_payload=8)
        with self.assertRaisesRegex(ValueError, "exceeds configured limit"):
            parser.feed(frame)

    def test_rejects_malformed_command_padding_and_trailing_bytes(self):
        frame = bytearray(encode_message(MAGIC, "ping", b""))
        frame[10] = ord("x")
        with self.assertRaisesRegex(ValueError, "after padding"):
            decode_message(bytes(frame), MAGIC)
        good = encode_message(MAGIC, "ping", b"")
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            decode_message(good + b"x", MAGIC)

    def test_rejects_invalid_commands(self):
        for command in ("", "UPPER", "has space", "long_command_123"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    encode_message(MAGIC, command, b"")

    def test_checksum_matches_sha256d_prefix(self):
        payload = b"blackroot"
        frame = encode_message(MAGIC, "hello", payload)
        self.assertEqual(frame[20:24], sha256d(payload)[:4])


if __name__ == "__main__":
    unittest.main()
