import contextlib
import io
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

import auto_ec as ec


class ModeTests(unittest.TestCase):
    def test_heating_and_cooling_preserve_both_hysteresis_bands(self):
        args = ec.parse_args([])
        mode = None
        samples = [
            (30, ec.MODE_OFF),
            (49, ec.MODE_OFF),
            (50, ec.MODE_NORMAL),
            (45, ec.MODE_NORMAL),
            (40, ec.MODE_OFF),
            (70, ec.MODE_EXTREME),
            (61, ec.MODE_EXTREME),
            (60, ec.MODE_NORMAL),
            (40, ec.MODE_OFF),
            (75, ec.MODE_EXTREME),
            (45, ec.MODE_NORMAL),  # A large drop must still honor normal-off.
            (39, ec.MODE_OFF),
        ]
        for temp, expected in samples:
            with self.subTest(mode=mode, temp=temp):
                mode = ec.choose_mode(mode, temp, args)
                self.assertEqual(mode, expected)

    def test_unavailable_temperature_always_requests_extreme(self):
        for mode in (None, ec.MODE_OFF, ec.MODE_NORMAL, ec.MODE_EXTREME):
            with self.subTest(mode=mode):
                self.assertEqual(ec.choose_mode(mode, None, ec.parse_args([])),
                                 ec.MODE_EXTREME)

    def test_startup_uses_current_temperature(self):
        for temp, expected in ((35, ec.MODE_OFF), (55, ec.MODE_NORMAL),
                               (80, ec.MODE_EXTREME)):
            with self.subTest(temp=temp):
                self.assertEqual(ec.choose_mode(None, temp, ec.parse_args([])), expected)

    def test_invalid_configuration_is_rejected(self):
        for argv in (["--interval", "0"], ["--interval", "-1"],
                     ["--temp-off", "70"], ["--temp-normal-off", "50"],
                     ["--temp-normal-on", "65"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    ec.parse_args(argv)
                self.assertEqual(error.exception.code, 2)


class ECWriteTests(unittest.TestCase):
    @patch("auto_ec.os.pwrite", return_value=1)
    @patch("auto_ec.os.pread", return_value=b"\x00")
    def test_complete_transaction_waits_for_final_byte(self, read, write):
        ec.ec_write(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_EXTREME)
        self.assertEqual(read.call_count, 4)
        self.assertEqual(write.call_args_list, [
            call(9, b"\x81", ec.EC_SC),
            call(9, b"\xbd", ec.EC_DATA),
            call(9, b"\x40", ec.EC_DATA),
        ])

    @patch("auto_ec.time.monotonic", side_effect=[0, 0, 0, 0, 0.11])
    @patch("auto_ec.os.pwrite", return_value=1)
    @patch("auto_ec.os.pread", side_effect=[b"\x00"] * 3 + [b"\x02"])
    def test_final_byte_timeout_is_a_failure(self, read, write, clock):
        with self.assertRaises(TimeoutError):
            ec.ec_write(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_EXTREME)

    @patch("auto_ec.os.pread", return_value=b"")
    @patch("auto_ec.os.pwrite")
    def test_short_status_read_aborts_before_writing(self, write, read):
        with self.assertRaisesRegex(OSError, "Short read"):
            ec.ec_write(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_EXTREME)
        write.assert_not_called()

    @patch("auto_ec.os.pread", return_value=b"\x00")
    @patch("auto_ec.os.pwrite", return_value=0)
    def test_short_write_aborts_transaction(self, write, read):
        with self.assertRaisesRegex(OSError, "Short write"):
            ec.ec_write(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_EXTREME)
        self.assertEqual(write.call_count, 1)

    @patch("auto_ec.time.sleep")
    @patch("auto_ec.os.pread", side_effect=PermissionError("denied"))
    def test_io_errors_are_not_hidden_as_timeouts(self, read, sleep):
        with self.assertRaises(PermissionError):
            ec.ec_wait(9, ec.IBF, 0)
        sleep.assert_not_called()


class FanControllerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("auto_ec.log"))
        self.write = self.enterContext(patch("auto_ec.ec_write"))
        self.fans = ec.FanController(9)

    def test_initial_off_is_written_but_unchanged_modes_are_not(self):
        self.assertTrue(self.fans.set_mode(ec.MODE_OFF, "startup"))
        self.assertTrue(self.fans.set_mode(ec.MODE_OFF, "next sample"))
        self.write.assert_called_once_with(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_OFF)

    def test_failed_write_preserves_state_and_is_retried(self):
        self.write.side_effect = [TimeoutError("busy"), None]
        self.assertFalse(self.fans.set_mode(ec.MODE_EXTREME, "hot"))
        self.assertIsNone(self.fans.mode)
        self.assertTrue(self.fans.set_mode(ec.MODE_EXTREME, "hot"))
        self.assertEqual(self.fans.mode, ec.MODE_EXTREME)
        self.assertEqual(self.write.call_count, 2)

    def test_partial_failure_forces_reapplication_of_previous_mode(self):
        self.fans.set_mode(ec.MODE_NORMAL, "warm")
        self.write.side_effect = [OSError("partial write"), None]
        self.assertFalse(self.fans.set_mode(ec.MODE_EXTREME, "hot"))
        self.assertEqual(self.fans.mode, ec.MODE_NORMAL)
        self.assertTrue(self.fans.set_mode(ec.MODE_NORMAL, "cooled"))
        self.assertEqual(self.write.call_count, 3)

    def test_shutdown_handles_ec_failure(self):
        self.fans.set_mode(ec.MODE_EXTREME, "hot")
        self.write.side_effect = OSError("device unavailable")
        self.fans.stop()
        self.write.assert_called_with(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_OFF)


class SensorTests(unittest.TestCase):
    def test_sensor_is_rediscovered_after_disappearing(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "temp1"
            second = Path(directory) / "temp2"
            first.write_text("72000\n")
            second.write_text("55000\n")
            with patch("auto_ec.get_cpu_temp_path", side_effect=[str(first), str(second)]):
                sensor = ec.TemperatureSensor()
                self.assertEqual(sensor.read(), 72)
                first.unlink()
                with self.assertRaises(OSError):
                    sensor.read()
                self.assertEqual(sensor.read(), 55)

    def test_bad_samples_fail_instead_of_becoming_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temp"
            with patch("auto_ec.get_cpu_temp_path", return_value=str(path)):
                sensor = ec.TemperatureSensor()
                for content in (b"", b"garbage", b"60\xff000"):
                    with self.subTest(content=content):
                        path.write_bytes(content)
                        with self.assertRaises(ValueError):
                            sensor.read()
                        self.assertIsNone(sensor.path)
                path.write_bytes(b"60125\n")
                self.assertEqual(sensor.read(), 60.125)

    def test_discovery_requires_exact_driver_and_existing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            names = []
            for index, driver in enumerate(("not-k10temp", "k10temp", "k10temp")):
                hwmon = Path(directory) / f"hwmon{index}"
                hwmon.mkdir()
                name = hwmon / "name"
                name.write_text(driver + "\n")
                if index != 1:
                    (hwmon / "temp1_input").write_text("50000")
                names.append(str(name))
            with patch("auto_ec.glob.glob", return_value=names):
                self.assertEqual(ec.get_cpu_temp_path(),
                                 str(Path(directory) / "hwmon2" / "temp1_input"))


class LifecycleTests(unittest.TestCase):
    @patch("auto_ec.log")
    @patch("auto_ec.ec_write")
    def test_sensor_failure_and_recovery_drive_fail_safe_hysteresis(self, write, log):
        sensor = Mock()
        sensor.read.side_effect = [55, OSError("gone"), ValueError("empty"), 65, 60, 39]
        shutdown = Mock()
        shutdown.is_set.side_effect = [False] * 6 + [True]
        ec.control_loop(ec.FanController(9), sensor, ec.parse_args([]), shutdown)
        self.assertEqual([args.args[2] for args in write.call_args_list],
                         [ec.MODE_NORMAL, ec.MODE_EXTREME, ec.MODE_NORMAL, ec.MODE_OFF])
        messages = [args.args[0] for args in log.call_args_list]
        self.assertEqual(sum("Temperature read failed" in msg for msg in messages), 1)
        self.assertEqual(sum("recovered" in msg for msg in messages), 1)

    @patch("auto_ec.log")
    @patch("auto_ec.ec_write")
    def test_missing_sensor_waits_without_writing_then_applies_sample(self, write, log):
        sensor = Mock()
        sensor.read.side_effect = [OSError("missing"), OSError("missing"), 55]
        shutdown = Mock()
        shutdown.is_set.side_effect = [False, False, False, True]
        ec.control_loop(ec.FanController(9), sensor, ec.parse_args([]), shutdown)
        write.assert_called_once_with(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_NORMAL)
        messages = [args.args[0] for args in log.call_args_list]
        self.assertEqual(sum("waiting" in msg for msg in messages), 1)
        self.assertFalse(any("EXTREME" in msg for msg in messages))

    @patch("auto_ec.time.monotonic", side_effect=[0, 30, 60])
    @patch("auto_ec.log")
    @patch("auto_ec.ec_write")
    def test_failure_log_repeats_only_after_one_minute(self, write, log, clock):
        sensor = Mock()
        sensor.read.side_effect = [55, OSError("gone"), OSError("gone"), OSError("gone")]
        shutdown = Mock()
        shutdown.is_set.side_effect = [False] * 4 + [True]
        ec.control_loop(ec.FanController(9), sensor, ec.parse_args([]), shutdown)
        messages = [args.args[0] for args in log.call_args_list]
        self.assertEqual(sum("Temperature read failed" in msg for msg in messages), 2)
        self.assertEqual(write.call_args_list, [
            call(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_NORMAL),
            call(9, ec.EXTREME_COOLING_REGISTER, ec.MODE_EXTREME),
        ])

    @patch("auto_ec.log")
    def test_ec_reset_failure_still_closes_port_and_releases_lock(self, log):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "auto_ec.pid")
            lock = ec.single_instance(path)
            real_close = os.close

            def closing(fd):
                if fd != 9:
                    real_close(fd)

            with patch("auto_ec.single_instance", return_value=lock), \
                    patch("auto_ec.TemperatureSensor"), \
                    patch("auto_ec.os.open", return_value=9), \
                    patch("auto_ec.os.close", side_effect=closing) as close, \
                    patch("auto_ec.ec_write", side_effect=OSError("device gone")), \
                    patch("auto_ec.control_loop", side_effect=RuntimeError("loop failed")):
                with self.assertRaisesRegex(RuntimeError, "loop failed"):
                    ec.run(ec.parse_args([]))
                close.assert_any_call(9)
            with ec.single_instance(path):
                pass

    def test_real_sigterm_interrupts_wait(self):
        shutdown = ec.StopSignal()
        previous_wakeup = shutdown.install_wakeup()
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: shutdown.set())
        try:
            def send_term():
                time.sleep(0.1)
                os.kill(os.getpid(), signal.SIGTERM)

            threading.Thread(target=send_term, daemon=True).start()
            started = time.monotonic()
            woke = shutdown.wait(30)
            elapsed = time.monotonic() - started
        finally:
            signal.signal(signal.SIGTERM, previous)
            signal.set_wakeup_fd(previous_wakeup)
            shutdown.close()
        self.assertTrue(woke)
        self.assertLess(elapsed, 5)

    def test_lock_excludes_second_instance_and_survives_stale_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auto_ec.pid"
            path.write_text("stale PID")
            with ec.single_instance(str(path)):
                self.assertEqual(path.read_text(), str(os.getpid()))
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with ec.single_instance(str(path)):
                        self.fail("second instance acquired lock")
            self.assertTrue(path.exists())
            with ec.single_instance(str(path)):
                pass


if __name__ == "__main__":
    unittest.main()
