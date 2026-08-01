import os
import socket
import subprocess
import sys
import time

from flask import Blueprint, redirect, url_for

from services.auth import login_required

launcher_bp = Blueprint("launcher", __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAYROLL_APP_DIR = os.path.join(_BASE, "Payroll App")
PAYROLL_PORT = 5001


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@launcher_bp.route("/launch/payroll")
@login_required
def launch_payroll():
    if not _port_open("127.0.0.1", PAYROLL_PORT):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen(
            [sys.executable, "payroll.py"],
            cwd=PAYROLL_APP_DIR,
            creationflags=flags,
        )
        for _ in range(12):
            time.sleep(0.5)
            if _port_open("127.0.0.1", PAYROLL_PORT):
                break

    return redirect(f"http://localhost:{PAYROLL_PORT}")
