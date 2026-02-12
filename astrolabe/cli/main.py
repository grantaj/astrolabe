import argparse
import sys
from datetime import datetime
import socket
from astrolabe import __version__
import socket
import subprocess
from astrolabe.config import load_config

def run_doctor():
    config = load_config()

    def check_indi_server():
    
        try:
            with socket.create_connection((config.indi_host, config.indi_port), timeout=2):
                return {"ok": True, "detail": "reachable"}
        except (ConnectionRefusedError, socket.timeout, OSError):
            return {"ok": False, "detail": "not reachable"}
        
    def check_solver():
        solver_binary = config.solver_binary

        try:
            result = subprocess.run(
                [solver_binary, "-h"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
            )
            if result.returncode == 0:
                return {"ok": True, "detail": "responds to -h"}
            else:
                return {"ok": False, "detail": "returned non-zero"}
        except FileNotFoundError:
            return {"ok": False, "detail": "not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "timeout"}

    def check_config():
        try:
            config = load_config()
            return {"ok": True, "detail": "loaded (defaults applied if missing)"}
        except Exception as e:
            return {"ok": False, "detail": f"invalid config: {e}"}


    checks = {
        "config": check_config(),
        "indi_server": check_indi_server(),
        "solver": check_solver(),
        "camera_backend": {"ok": False, "detail": "not implemented"},
        "mount_backend": {"ok": False, "detail": "not implemented"},
    }

    ok = all(c["ok"] for c in checks.values())

    print("Astrolabe Doctor Report")
    print("=======================")

    for name, result in checks.items():
        status = "OK" if result["ok"] else "MISSING"
        print(f"{name:20} : {status} ({result['detail']})")

    if ok:
        print("\nSystem ready.")
        return 0
    else:
        print("\nSome components are missing or not configured.")
        return 1



def main():
    parser = argparse.ArgumentParser(prog="astrolabe")
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Run system diagnostics")

    args = parser.parse_args()

    if args.version:
        print(f"Astrolabe {__version__}")
        return 0

    if args.command == "doctor":
        return run_doctor()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
