#!/usr/bin/env python3
"""Sense AI / RPLIDAR C1: timestamped host-reception scan logger (v3, optional warm-up).

Uses the existing official SLAMTEC `ultra_simple` executable via a macOS
pseudo-terminal so its printed output is promptly available to Python.
Timestamps describe when the Mac received text chunks, NOT laser emission times.
SIGINT shutdown drains the PTY so the SDK can reach its stop/motor-off code.
Requires only the Python standard library (no pip installs).
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import sys
import time

BASE = Path.home() / "EE-Build-Lab" / "Sense-AI"
EXECUTABLE = BASE / "rplidar_sdk/output/Darwin/Release/ultra_simple"
PATTERN = re.compile(r"(S\s+)?theta:\s*([\d.]+)\s+Dist:\s*([\d.]+)\s+Q:\s*(\d+)")


def stop_sdk_gracefully(process, master, seconds=8.0):
    """Send SIGINT and KEEP DRAINING the PTY until the child exits.

    The SLAMTEC demo writes scan text rapidly. If the parent stops reading
    before child shutdown, the PTY output buffer fills and the demo can block
    inside printf() before it reaches its signal-handler check. The first
    logger version accidentally did this.
    """
    if process.poll() is not None:
        return "already_exited", process.returncode

    process.send_signal(signal.SIGINT)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        # Read/discard any post-capture output to prevent a blocked printf().
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                os.read(master, 65536)
            except OSError:
                pass  # PTY may report EIO when the child exits.
        if process.poll() is not None:
            return "clean_sigint", process.returncode

    # Fallback only; this bypasses the demo application's motor-stop code.
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return "forced_termination", process.returncode
    return "clean_sigint", process.returncode


def run():
    parser = argparse.ArgumentParser(description="Capture timestamped RPLIDAR scan text into CSV")
    parser.add_argument("--port", default="/dev/cu.usbserial-110", help="Verified macOS serial port")
    parser.add_argument("--seconds", type=float, default=8.0, help="Capture duration after warm-up")
    parser.add_argument("--warmup-seconds", type=float, default=0.0, help="Discard data during continuous sensor warm-up")
    parser.add_argument("--output", type=Path, default=BASE / "data/c1_050cm_timestamped_v2.csv")
    parser.add_argument("--reference-mm", type=float, default=500.0,
                        help="Independently measured reference distance in mm")
    parser.add_argument("--reference-uncertainty-mm", type=float, default=2.0,
                        help="Manual reference uncertainty in mm")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.warmup_seconds < 0:
        parser.error("--warmup-seconds cannot be negative")
    if not EXECUTABLE.is_file():
        parser.error(f"SDK executable not found: {EXECUTABLE}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    command = [str(EXECUTABLE), "--channel", "--serial", args.port, "460800"]
    print(f"Starting SLAMTEC SDK on {args.port}; waiting for first measurement...", flush=True)
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
    finally:
        os.close(slave)

    capture_start = None
    first_measurement_time = None
    boot_start = time.monotonic()
    buffer = b""
    n = n_valid = n_candidate = 0
    sweep_index = 0
    previous_angle = None
    run_started_utc = None
    failure = None
    try:
        with args.output.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "sample_index", "host_received_utc", "host_elapsed_s", "sweep_index",
                "angle_deg", "distance_mm", "quality", "valid_distance",
                "scan_sync_flag", "candidate_355_to_5_deg",
            ])
            while True:
                if capture_start is not None and time.monotonic() - capture_start >= args.seconds:
                    break
                if first_measurement_time is None and time.monotonic() - boot_start > 20:
                    failure = "No measurements received within 20 seconds; check connection and port."
                    break
                ready, _, _ = select.select([master], [], [], 0.2)
                if not ready:
                    if process.poll() is not None:
                        failure = f"SDK exited early with return code {process.returncode}."
                        break
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    failure = "SDK output stream closed."
                    break
                if not chunk:
                    failure = "SDK output stream ended."
                    break
                # Clock at receipt of the SDK's text chunk, not at optical acquisition.
                received_monotonic = time.monotonic()
                received_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="replace").strip()
                    match = PATTERN.search(line)
                    if match is None:
                        if "Error" in line or "health status" in line:
                            print("SDK:", line)
                        continue
                    if first_measurement_time is None:
                        first_measurement_time = received_monotonic
                        if args.warmup_seconds:
                            print(f"Warming continuously for {args.warmup_seconds:g} seconds; discarding warm-up measurements...", flush=True)
                    if capture_start is None:
                        if received_monotonic - first_measurement_time < args.warmup_seconds:
                            continue
                        capture_start = received_monotonic
                        run_started_utc = received_utc
                        print(f"Warm-up complete; recording ~{args.seconds:g} seconds...", flush=True)
                    angle = float(match.group(2))
                    distance = float(match.group(3))
                    quality = int(match.group(4))
                    valid = distance > 0
                    if previous_angle is not None and previous_angle > 300 and angle < 60:
                        sweep_index += 1
                    previous_angle = angle
                    in_candidate_sector = angle >= 355 or angle <= 5
                    writer.writerow([
                        n, received_utc, round(received_monotonic - capture_start, 6),
                        sweep_index, angle, distance, quality, int(valid),
                        int(bool(match.group(1))), int(in_candidate_sector),
                    ])
                    n += 1
                    n_valid += int(valid)
                    n_candidate += int(valid and in_candidate_sector)
    except KeyboardInterrupt:
        print("\nInterrupted by user; finishing CSV.", flush=True)
    finally:
        # IMPORTANT: continue draining the SDK output after SIGINT. Otherwise
        # the demo can block in printf() and never execute stop()/motor off.
        stop_method, stop_return_code = stop_sdk_gracefully(process, master)
        os.close(master)

    metadata = {
        "model": "RPLIDAR C1M1",
        "capture_date_utc": run_started_utc,
        "timestamp_definition": "macOS host receipt of printed SDK output; NOT laser measurement time",
        "reference_distance_mm": args.reference_mm,
        "reference_uncertainty_mm": args.reference_uncertainty_mm,
        "reference_note": "Measured manually after book was repositioned; confirm setup before formal analysis",
        "device_port": args.port,
        "baudrate": 460800,
        "sdk_executable": str(EXECUTABLE),
        "planned_capture_seconds": args.seconds,
        "planned_warmup_seconds": args.warmup_seconds,
        "samples_saved": n,
        "positive_distance_samples": n_valid,
        "positive_distance_candidate_sector": n_candidate,
        "candidate_sector_note": "355 to 360 and 0 to 5 degrees, preliminary book-associated angular region",
        "warmup_note": "Warm-up is measured by host monotonic time from first reported measurement; warm-up samples discarded, motor kept running",
        "sdk_shutdown_method": stop_method,
        "sdk_exit_code": stop_return_code,
        "timestamps_are_per_output_chunk": True,
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Saved CSV: {args.output}")
    print(f"Saved metadata: {args.output.with_suffix('.json')}")
    print(f"Samples: {n}; valid distances: {n_valid}; candidate-sector valid: {n_candidate}")
    print(f"SDK shutdown: {stop_method} (exit code {stop_return_code})")
    if stop_method == "forced_termination":
        print("WARNING: Motor-stop command may not have executed. Check motor; disconnect USB power if still rotating.")
    if failure:
        print(f"NOTE: {failure}")
    if n == 0:
        raise SystemExit("No scan measurements were recorded; share the Terminal output for debugging.")


if __name__ == "__main__":
    run()
