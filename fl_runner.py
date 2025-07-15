#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FL Runner Service - Federated Learning Process Orchestrator

This service manages the lifecycle of Flower federated learning processes based on
commands received through DataClay. It operates as a standalone orchestrator without
BentoML integration, as model synchronization is handled by the dedicated model_sync service.

Key responsibilities:
- Monitor DataClay for FL training commands
- Launch and manage Flower processes
- Capture and report training logs and results
- Handle graceful shutdown of FL processes

"""

from __future__ import annotations

import inspect
import os
import signal
import subprocess
import threading
import time
from queue import Queue
from typing import Optional, Dict, Any, List

from dataclay.client.api import init
from dataclay.exceptions import DataClayException

from organizer_fl import OrganizerFL, Parameters

__author__ = "Sebastian Cajas Ordoñez, Anastasios Kaltakis"
__version__ = "1.0.0"
__status__ = "Production"

# Environment configuration with validation
ICOSFL_PATH = os.getenv("ICOSFL_PATH")
if ICOSFL_PATH is None:
    raise ValueError(
        "Environment variable ICOSFL_PATH is not set. "
        "Please set it to the path of the Flower configuration."
    )

# Validate Flower configuration directory exists
if not os.path.exists(ICOSFL_PATH):
    raise ValueError(f"ICOSFL_PATH directory does not exist: {ICOSFL_PATH}")

print(f"[FL Runner] Using Flower configuration from: {ICOSFL_PATH}")

# Model metric configuration
MODEL_METRIC = os.getenv("MODEL_METRIC", "cpu_usage")
VALID_METRICS = ["cpu_usage", "memory_usage", "power_consumption"]
if MODEL_METRIC not in VALID_METRICS:
    raise ValueError(
        f"Invalid MODEL_METRIC: {MODEL_METRIC}. "
        f"Must be one of {', '.join(VALID_METRICS)}."
    )

print(f"[FL Runner] Configured for metric: {MODEL_METRIC}")

# Initialize DataClay connection
init()
print("[FL Runner] DataClay client initialized")

# Global process management variables
LOG_QUEUE: Queue[str] = Queue()
flower_process: Optional[subprocess.Popen] = None
log_thread: Optional[threading.Thread] = None


def stream_process_output(proc: subprocess.Popen) -> None:
    """
    Stream subprocess output to both console and log queue.

    This function runs in a separate thread to capture Flower process output
    in real-time without blocking the main orchestration loop.

    Args:
        proc: The subprocess.Popen instance to monitor
    """
    try:
        with proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                if not line:
                    break

                text = line.decode('utf-8', errors='replace').rstrip()
                LOG_QUEUE.put(text)
                print(f"[Flower] {text}", flush=True)

    except Exception as e:
        error_msg = f"Error streaming process output: {e}"
        LOG_QUEUE.put(error_msg)
        print(f"[FL Runner] {error_msg}", flush=True)


def drain_logs() -> List[str]:
    """
    Extract all pending log messages from the queue.

    Returns:
        List of log messages accumulated since last drain
    """
    lines: List[str] = []
    while not LOG_QUEUE.empty():
        try:
            lines.append(LOG_QUEUE.get_nowait())
        except:
            break
    return lines


def build_flower_command(params: Parameters) -> List[str]:
    """
    Construct Flower command with appropriate parameters.

    Args:
        params: Parameters object containing FL configuration

    Returns:
        Command list ready for subprocess execution
    """
    cmd: List[str] = ["flwr", "run", ICOSFL_PATH, "remote-deployment"]

    # Add streaming flag if requested
    if params.use_stream:
        cmd.append("--stream")

    # Add run configuration parameters
    if params.run_config:
        # Filter out None values and format configuration
        run_config_str = " ".join(
            f"{k}={v}" for k, v in params.run_config.items()
            if v is not None
        )
        if run_config_str:
            cmd.extend(["--run-config", run_config_str])

    return cmd


def wait_for_organizer() -> OrganizerFL:
    """
    Wait for OrganizerFL to become available in DataClay.

    Returns:
        Connected OrganizerFL instance
    """
    while True:
        try:
            org: OrganizerFL = OrganizerFL.get_by_alias("global_organizer_fl")
            print("[FL Runner] Successfully connected to OrganizerFL")
            return org
        except DataClayException:
            print("[FL Runner] Waiting for OrganizerFL to become available...")
            time.sleep(1)


def handle_start_command(params: Parameters) -> None:
    """
    Handle 'start' command to launch Flower process.

    Args:
        params: Parameters containing FL configuration
    """
    global flower_process, log_thread

    # Check if process is already running
    if flower_process and flower_process.poll() is None:
        print("[FL Runner] ⚠ Flower process already running - ignoring duplicate 'start' command")
        return

    # Build and execute Flower command
    cmd = build_flower_command(params)
    print(f"[FL Runner] ➡️  Launching Flower with command: {' '.join(cmd)}")

    try:
        flower_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=False
        )

        # Start log streaming thread
        log_thread = threading.Thread(
            target=stream_process_output,
            args=(flower_process,),
            daemon=True,
            name="FlowerLogStreamer"
        )
        log_thread.start()

        print(f"[FL Runner] ✓ Flower process started with PID: {flower_process.pid}")

    except Exception as e:
        print(f"[FL Runner] ❌ Failed to start Flower process: {e}")
        flower_process = None
        log_thread = None


def handle_stop_command(org: OrganizerFL) -> None:
    """
    Handle 'stop' command to gracefully terminate Flower process.

    Args:
        org: OrganizerFL instance for sending results
    """
    global flower_process, log_thread

    if not flower_process or flower_process.poll() is not None:
        print("[FL Runner] No Flower process running to stop")
        return

    print(f"[FL Runner] ⏹  Stopping Flower process (PID: {flower_process.pid})...")

    # Attempt graceful shutdown with SIGINT
    flower_process.send_signal(signal.SIGINT)

    try:
        flower_process.wait(timeout=10)
        print("[FL Runner] ✓ Flower process terminated gracefully")
    except subprocess.TimeoutExpired:
        print("[FL Runner] ⚠ Flower did not exit gracefully, forcing termination...")
        flower_process.terminate()

        try:
            flower_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("[FL Runner] ⚠ Force termination failed, killing process...")
            flower_process.kill()
            flower_process.wait()

    # Collect final logs and send results
    finalize_process_results(org)


def finalize_process_results(org: OrganizerFL) -> None:
    """
    Collect final logs and send results to organizer.

    Args:
        org: OrganizerFL instance for sending results
    """
    global flower_process, log_thread

    if not flower_process:
        return

    # Collect remaining logs
    runtime_log = "\n".join(drain_logs())

    # Prepare results dictionary
    results = {
        "returncode": flower_process.returncode,
        "log_tail": runtime_log[-10_000:],  # Last 10K characters
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metric": MODEL_METRIC
    }

    print(f"[FL Runner] Process finished with return code: {flower_process.returncode}")

    # Send results to organizer
    try:
        org.send_results(results)
        print("[FL Runner] ✓ Results sent to organizer")
    except Exception as e:
        print(f"[FL Runner] ❌ Failed to send results: {e}")

    # Clean up
    flower_process = None
    if log_thread and log_thread.is_alive():
        log_thread.join(timeout=2)
    log_thread = None

    # Note: Model synchronization to BentoML is handled by model_sync service
    print("[FL Runner] ℹ Model synchronization will be handled by model_sync service")


def main_orchestration_loop(org: OrganizerFL) -> None:
    """
    Main orchestration loop for FL process management.

    Continuously polls for commands and manages Flower process lifecycle.

    Args:
        org: Connected OrganizerFL instance
    """
    global flower_process

    print("[FL Runner] Starting main orchestration loop...")

    while True:
        try:
            # Check for new commands
            params: Optional[Parameters] = org.get_trigger()

            if params:
                print(f"[FL Runner] Received command: {params.action}")

                if params.action == "start":
                    handle_start_command(params)

                elif params.action == "stop":
                    handle_stop_command(org)

                else:
                    print(f"[FL Runner] ⚠ Unknown action: {params.action}")

            # Check if process exited unexpectedly
            if flower_process and flower_process.poll() is not None:
                print("[FL Runner] ⚠ Flower process exited unexpectedly")
                finalize_process_results(org)

            # Drain any accumulated logs
            drain_logs()

        except Exception as e:
            print(f"[FL Runner] ❌ Error in orchestration loop: {e}")

        # Brief sleep to prevent CPU spinning
        time.sleep(0.5)


def main() -> None:
    """
    Main entry point for FL Runner service.
    """
    print(f"[FL Runner] Starting FL Runner Service v{__version__}")
    print(f"[FL Runner] Configuration:")
    print(f"  - ICOSFL_PATH: {ICOSFL_PATH}")
    print(f"  - MODEL_METRIC: {MODEL_METRIC}")
    print(f"  - DC_PROXY_HOST: {os.getenv('DC_PROXY_HOST', 'not set')}")
    print(f"  - DC_DATASET: {os.getenv('DC_DATASET', 'not set')}")

    # Wait for and connect to organizer
    org = wait_for_organizer()

    # Start main loop
    try:
        main_orchestration_loop(org)
    except KeyboardInterrupt:
        print("\n[FL Runner] Received interrupt signal, shutting down...")
        if flower_process and flower_process.poll() is None:
            handle_stop_command(org)
        print("[FL Runner] Service terminated")


if __name__ == "__main__":
    main()
