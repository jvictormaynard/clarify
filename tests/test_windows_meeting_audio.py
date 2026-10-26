"""Exercise the WASAPI boundary with synthetic COM objects, never a device."""

import ctypes as C
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import windows_meeting_audio as audio
from shared.meeting_contract import MeetingError


class FakeCom:
    def __init__(self, failures=(), init_result=1):
        self.failures = set(failures)
        self.hresults = {}
        self.events = []
        self.signatures = []
        self.methods = {}
        self.keepalive = []
        self.names = {}
        self.format = audio.WaveFormat(1, 1, 16000, 32000, 2, 16, 0)
        self.identifier = C.create_unicode_buffer("fixture-endpoint")
        self.raw = C.create_string_buffer(b"\x01\x00" * 160)
        self.packet_pending = True
        for name in ("enumerator", "device", "client", "capture"):
            table = (C.c_void_p * 15)()
            for index in range(15):
                address = len(self.methods) + 1
                self.methods[address] = (name, index)
                table[index] = address
            interface = (C.c_void_p * 1)(C.addressof(table))
            pointer = C.cast(interface, C.c_void_p)
            self.names[pointer.value] = name
            self.keepalive.extend((table, interface, pointer))
            setattr(self, name, pointer)
        self.dll = Mock()
        self.dll.CoInitializeEx = Mock(
            side_effect=lambda *args: self.event("initialize", init_result)
        )
        self.dll.CoCreateInstance = Mock(side_effect=self.create)
        self.dll.CoTaskMemFree = Mock(side_effect=self.free)
        self.dll.CoUninitialize = Mock(side_effect=lambda: self.event("uninitialize"))

    def event(self, name, result=0):
        self.events.append(name)
        if name in self.failures:
            raise OSError("private fixture detail")
        return result

    @staticmethod
    def output(target, value):
        C.cast(target, C.POINTER(C.c_void_p))[0] = value

    def create(self, clsid, outer, context, iid, result):
        self.event("create")
        self.output(result, self.enumerator.value)
        return 0

    def free(self, pointer):
        self.event(
            "free_format" if pointer.value == C.addressof(self.format) else "free_id"
        )

    def prototype(self, result_type, *types):
        def bind(address):
            name, index = self.methods[address]
            self.signatures.append((name, index, result_type, types))
            return lambda pointer, *args: self.call(name, index, args)

        return bind

    def call(self, name, index, args):
        self.event((name, index))
        if (name, index) in self.hresults:
            return self.hresults[name, index]
        if index == 2:
            return 0xFFFFFFFF  # ULONG reference count, never an HRESULT.
        if (name, index) == ("enumerator", 4):
            self.flow_role = args[:2]
            self.output(args[-1], self.device.value)
        elif (name, index) == ("device", 5):
            self.output(args[0], C.addressof(self.identifier))
        elif (name, index) == ("device", 3):
            self.output(args[-1], self.client.value)
        elif (name, index) == ("client", 8):
            self.output(args[0], C.addressof(self.format))
        elif (name, index) == ("client", 3):
            self.stream_flags = args[1]
        elif (name, index) == ("client", 14):
            self.output(args[-1], self.capture.value)
        elif (name, index) == ("capture", 5):
            C.cast(args[0], C.POINTER(C.c_uint32))[0] = (
                160 if self.packet_pending else 0
            )
            if not self.packet_pending:
                self.stop.set()
        elif (name, index) == ("capture", 3):
            self.output(args[0], C.addressof(self.raw))
            C.cast(args[1], C.POINTER(C.c_uint32))[0] = 160
            C.cast(args[2], C.POINTER(C.c_uint32))[0] = 1  # discontinuity
            self.packet_pending = False
        return 0

    def run(self, source="system", packet=None):
        import threading

        self.stop = threading.Event()
        self.packet = packet or Mock()
        self.warning = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(audio.sys, "platform", "win32"))
            self.load = stack.enter_context(
                patch.object(C, "WinDLL", return_value=self.dll, create=True)
            )
            stack.enter_context(
                patch.object(C, "WINFUNCTYPE", side_effect=self.prototype, create=True)
            )
            # The old loader must never open the host's real COM library.
            stack.enter_context(
                patch.object(C, "OleDLL", return_value=self.dll, create=True)
            )
            audio.WasapiSource(source).run(self.stop, self.packet, self.warning)


class WasapiBoundaryTests(unittest.TestCase):
    def test_run_declares_abi_and_captures_synthetic_packet_for_both_sources(self):
        for source, role, flags in (
            ("microphone", (1, 2), 0),
            ("system", (0, 0), 0x20000),
        ):
            with self.subTest(source=source):
                com = FakeCom()
                com.run(source)
                com.load.assert_called_once_with("ole32")
                self.assertIs(com.dll.CoTaskMemFree.restype, None)
                self.assertEqual(com.dll.CoTaskMemFree.argtypes, [C.c_void_p])
                self.assertIs(com.dll.CoUninitialize.restype, None)
                self.assertEqual(com.dll.CoUninitialize.argtypes, [])
                for function in (com.dll.CoInitializeEx, com.dll.CoCreateInstance):
                    self.assertIs(function.restype, C.c_int32)
                self.assertEqual(
                    com.dll.CoInitializeEx.argtypes, [C.c_void_p, C.c_uint32]
                )
                self.assertEqual(
                    com.dll.CoCreateInstance.argtypes,
                    [
                        C.c_void_p,
                        C.c_void_p,
                        C.c_uint32,
                        C.c_void_p,
                        C.POINTER(C.c_void_p),
                    ],
                )
                for _, index, restype, _ in com.signatures:
                    self.assertIs(restype, C.c_uint32 if index == 2 else C.c_int32)
                self.assertEqual(com.flow_role, role)
                self.assertEqual(com.stream_flags, flags)
                com.packet.assert_called_once_with(b"\x01\x00" * 160, 16000)
                com.warning.assert_called_once_with("meeting.audio_gap")
                self.assertEqual(
                    com.events[-7:],
                    [
                        ("client", 11),
                        "free_format",
                        ("capture", 2),
                        ("client", 2),
                        ("device", 2),
                        ("enumerator", 2),
                        "uninitialize",
                    ],
                )

    def test_cleanup_attempts_every_release_after_stop_free_or_release_failure(self):
        for failures in (
            {("client", 11)},
            {"free_format"},
            {("capture", 2)},
            {"uninitialize"},
            {("client", 11), "free_format", ("capture", 2), ("client", 2)},
        ):
            with self.subTest(failures=failures):
                com = FakeCom(failures)
                with self.assertRaisesRegex(MeetingError, "meeting.capture_error"):
                    com.run()
                self.assertEqual(
                    com.events[-7:],
                    [
                        ("client", 11),
                        "free_format",
                        ("capture", 2),
                        ("client", 2),
                        ("device", 2),
                        ("enumerator", 2),
                        "uninitialize",
                    ],
                )

    def test_identifier_free_failure_still_releases_device_and_apartment(self):
        com = FakeCom({"free_id"})
        with self.assertRaises(OSError):
            com.run()
        self.assertEqual(
            com.events[-3:], [("device", 2), ("enumerator", 2), "uninitialize"]
        )

    def test_packet_failure_returns_buffer_and_cleans_all_interfaces(self):
        com = FakeCom({"free_format", ("capture", 2)})
        with self.assertRaisesRegex(MeetingError, "meeting.audio_format"):
            com.run(packet=Mock(side_effect=MeetingError("meeting.audio_format")))
        self.assertIn(("capture", 4), com.events)
        self.assertEqual(
            com.events[-3:], [("device", 2), ("enumerator", 2), "uninitialize"]
        )

    def test_failed_initialization_never_uninitializes_or_creates_interfaces(self):
        com = FakeCom(init_result=-2147417850)
        with self.assertRaisesRegex(MeetingError, "meeting.capture_error"):
            com.run()
        self.assertEqual(com.events, ["initialize"])

    def test_partial_startup_failure_releases_acquired_interfaces_without_stop(self):
        com = FakeCom({("client", 14), "free_format", ("client", 2)})
        with self.assertRaisesRegex(OSError, "private fixture detail"):
            com.run()
        self.assertNotIn(("client", 11), com.events)
        self.assertNotIn(("capture", 2), com.events)
        self.assertEqual(
            com.events[-5:],
            [
                "free_format",
                ("client", 2),
                ("device", 2),
                ("enumerator", 2),
                "uninitialize",
            ],
        )

    def test_failed_hresult_in_capture_still_closes_stream_and_apartment(self):
        com = FakeCom()
        com.hresults["capture", 5] = -2147467259
        with self.assertRaisesRegex(MeetingError, "meeting.capture_error"):
            com.run()
        com.packet.assert_not_called()
        self.assertEqual(
            com.events[-7:],
            [
                ("client", 11),
                "free_format",
                ("capture", 2),
                ("client", 2),
                ("device", 2),
                ("enumerator", 2),
                "uninitialize",
            ],
        )
