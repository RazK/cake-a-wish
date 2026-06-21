import os
import re
import socket
import sys
import urllib.request
from typing import Optional

import serial
from brother_ql.backends.helpers import send
from brother_ql.reader import interpret_response

# On Windows, add the libusb-package DLL directory so pyusb can find libusb-1.0.dll
# without requiring the user to install Zadig or any system driver.
if sys.platform == "win32":
    try:
        import libusb_package
        _dll_dir = os.path.dirname(libusb_package.__file__)
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_dll_dir)
    except Exception:
        pass

_INVALIDATE     = bytes(200)
_INITIALIZE     = bytes([0x1B, 0x40])
_STATUS_REQUEST = bytes([0x1B, 0x69, 0x53])


def _parse_http_status(html: str) -> Optional[dict]:
    """Parse the /home/status.html page and return a status dict compatible
    with interpret_response(), or None if the page can't be understood."""
    pairs = dict(re.findall(r'<dt>(.*?)</dt><dd>(.*?)</dd>', html))

    def clean(v: str) -> str:
        return re.sub(r'<[^>]+>', '', v).replace('&#32;', ' ').strip()

    media_status = clean(pairs.get('Media&#32;Status', ''))
    media_type_str = clean(pairs.get('Media&#32;Type', ''))
    device_status_raw = pairs.get('Device&#32;Status', '')
    ready = 'moniOk' in device_status_raw
    errors = []
    if 'moniError' in device_status_raw or 'moniWarn' in device_status_raw:
        errors = [clean(device_status_raw)]

    if not media_type_str:
        return None

    # Parse media type string into (type_name, width_mm, length_mm)
    # Continuous:  "62mm / 2.4""  →  width=62, length=0
    # Die-cut:     "29mm x 90mm"  →  width=29, length=90
    m_cont = re.match(r'(\d+)mm\s*/', media_type_str)
    m_die  = re.match(r'(\d+)mm\s*x\s*(\d+)mm', media_type_str, re.IGNORECASE)

    tape_present = 'not' in media_status.lower() and 'empty' in media_status.lower()
    if not tape_present:
        media_kind   = 'No media'
        media_width  = 0
        media_length = 0
    elif m_die:
        media_kind   = 'Die-cut labels'
        media_width  = int(m_die.group(1))
        media_length = int(m_die.group(2))
    elif m_cont:
        media_kind   = 'Continuous length tape'
        media_width  = int(m_cont.group(1))
        media_length = 0
    else:
        return None

    return {
        'status_type': 'Reply to status request',
        'phase_type':  'Waiting to receive' if ready else 'Unknown',
        'media_type':  media_kind,
        'media_width': media_width,
        'media_length': media_length,
        'errors':      errors,
    }


class BrotherPrinter:
    def __init__(self, ip: str, model: str = "QL-820NWB", password: Optional[str] = None):
        self.ip    = ip
        self.model = model

    def _http_status(self) -> Optional[dict]:
        """Fetch media/status info from the printer's built-in web page."""
        try:
            r = urllib.request.urlopen(
                f'http://{self.ip}/home/status.html', timeout=1.5
            )
            return _parse_http_status(r.read().decode('utf-8', errors='replace'))
        except Exception:
            return None

    def query_status(self) -> dict:
        """Return {'connected': bool, 'status': dict|None}.

        1. TCP connect to port 9100 → determines 'connected'.
        2. Try ESC i S for rich status (works on some models).
        3. If ESC i S gives no response, fall back to HTTP status page.
        """
        try:
            sock = socket.create_connection((self.ip, 9100), timeout=0.8)
        except Exception:
            return {"connected": False, "status": None}

        parsed = None
        try:
            sock.sendall(_INVALIDATE + _INITIALIZE + _STATUS_REQUEST)
            sock.settimeout(0.2)          # short timeout — fall back to HTTP fast
            data = b""
            while len(data) < 32:
                chunk = sock.recv(32 - len(data))
                if not chunk:
                    break
                data += chunk
            if len(data) >= 32:
                parsed = interpret_response(data)
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

        if parsed is None:
            parsed = self._http_status()

        return {"connected": True, "status": parsed}

    def send_instructions(self, instructions: bytes) -> dict:
        return send(
            instructions=instructions,
            printer_identifier=f"tcp://{self.ip}",
            backend_identifier="network",
            blocking=True,
        )


class BTBrotherPrinter:
    """Brother QL over Bluetooth serial (e.g. /dev/cu.QL-820NWB5742).

    Status queries are not supported over BT — connected means the device file
    can be opened. Label detection is unavailable; caller should use the fallback.
    """

    def __init__(self, device: str):
        self.device = device
        self.model  = "QL-820NWB"

    def query_status(self) -> dict:
        try:
            s = serial.Serial(self.device, baudrate=9600, timeout=0.5,
                              rtscts=False, dsrdtr=False)
            s.close()
            return {"connected": True, "status": None}
        except Exception:
            return {"connected": False, "status": None}

    def send_instructions(self, instructions: bytes) -> dict:
        # Prepend explicit invalidation + init: BT serial doesn't get a fresh
        # TCP connection per job, so the printer may carry state.
        payload = _INVALIDATE + _INITIALIZE + instructions
        s = serial.Serial(self.device, baudrate=115200, timeout=30,
                          rtscts=False, dsrdtr=False)
        try:
            s.write(payload)
            s.flush()
        finally:
            s.close()
        return {"did_print": True}


def find_usb_printer() -> Optional[str]:
    """Return the identifier of the first detected Brother USB printer, or None."""
    try:
        from brother_ql.backends.helpers import discover
        devices = discover('pyusb')
        if devices:
            return devices[0]['identifier']
    except Exception:
        pass
    return None


class USBBrotherPrinter:
    """Brother QL over USB (pyusb backend).

    Status is limited to presence detection — no media info available over USB.
    Passes the live usb.core.Device instance to send() to avoid identifier
    string-parsing issues in the backend.
    """

    def __init__(self, identifier: str):
        self.identifier = identifier
        self.model = "QL-820NWB"

    def _get_device(self):
        """Return the live usb.core.Device instance for this printer."""
        from brother_ql.backends.helpers import discover
        for d in discover('pyusb'):
            if d['identifier'] == self.identifier:
                return d['instance']
        return None

    def query_status(self) -> dict:
        try:
            connected = self._get_device() is not None
        except Exception:
            connected = False
        return {"connected": connected, "status": None}

    def send_instructions(self, instructions: bytes) -> dict:
        device = self._get_device()
        if device is None:
            raise RuntimeError("USB printer not found")
        return send(
            instructions=instructions,
            printer_identifier=device,
            backend_identifier="pyusb",
            blocking=True,
        )
