"""WiFi and USB connection implementations for Brother QL label printers."""

import re
import socket
import urllib.request
from typing import Optional

from brother_ql.backends.helpers import discover, send
from brother_ql.reader import interpret_response

# macOS refuses to let libusb detach its kernel driver (EACCES), but the
# printer still works after claim_interface. Suppress only EACCES so the
# rest of the pyusb backend proceeds; other errors (EBUSY, ENODEV) still raise.
try:
    import errno as _errno
    import usb.core as _usb_core
    from usb.core import USBError as _USBError
    _real_detach = _usb_core.Device.detach_kernel_driver
    def _safe_detach(self, interface):
        try:
            return _real_detach(self, interface)
        except _USBError as e:
            if e.errno != _errno.EACCES:
                raise
    _usb_core.Device.detach_kernel_driver = _safe_detach
except Exception:
    pass

_INVALIDATE     = bytes(200)
_INITIALIZE     = bytes([0x1B, 0x40])
_STATUS_REQUEST = bytes([0x1B, 0x69, 0x53])


def _parse_http_status(html: str) -> Optional[dict]:
    """Parse /home/status.html into a dict compatible with interpret_response(), or None."""
    pairs = dict(re.findall(r'<dt>(.*?)</dt><dd>(.*?)</dd>', html))

    def clean(v: str) -> str:
        return re.sub(r'<[^>]+>', '', v).replace('&#32;', ' ').strip()

    media_status      = clean(pairs.get('Media&#32;Status', ''))
    media_type_str    = clean(pairs.get('Media&#32;Type', ''))
    device_status_raw = pairs.get('Device&#32;Status', '')
    ready             = 'moniOk' in device_status_raw
    errors = [clean(device_status_raw)] if ('moniError' in device_status_raw or 'moniWarn' in device_status_raw) else []

    if not media_type_str:
        return None

    m_cont = re.match(r'(\d+)mm\s*/', media_type_str)
    m_die  = re.match(r'(\d+)mm\s*x\s*(\d+)mm', media_type_str, re.IGNORECASE)

    tape_present = 'not' in media_status.lower() and 'empty' in media_status.lower()
    if not tape_present:
        media_kind, media_width, media_length = 'No media', 0, 0
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
        'status_type':  'Reply to status request',
        'phase_type':   'Waiting to receive' if ready else 'Unknown',
        'media_type':   media_kind,
        'media_width':  media_width,
        'media_length': media_length,
        'errors':       errors,
    }


def find_usb_printer() -> Optional[str]:
    """Return the identifier of the first detected Brother USB printer, or None."""
    try:
        devices = discover('pyusb')
        if devices:
            return devices[0]['identifier']
    except Exception:
        pass
    return None


class WifiConnection:
    """Brother QL over TCP/9100 with HTTP status page fallback."""

    def __init__(self, ip: str, model: str = "QL-820NWB"):
        self.ip    = ip
        self.model = model

    def _http_status(self) -> Optional[dict]:
        try:
            r = urllib.request.urlopen(f'http://{self.ip}/home/status.html', timeout=1.5)
            return _parse_http_status(r.read().decode('utf-8', errors='replace'))
        except Exception:
            return None

    def query_status(self) -> dict:
        try:
            sock = socket.create_connection((self.ip, 9100), timeout=0.8)
        except Exception:
            return {"connected": False, "status": None}

        parsed = None
        try:
            sock.sendall(_INVALIDATE + _INITIALIZE + _STATUS_REQUEST)
            sock.settimeout(0.2)
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

    def send_job(self, instructions: bytes) -> dict:
        return send(
            instructions=instructions,
            printer_identifier=f"tcp://{self.ip}",
            backend_identifier="network",
            blocking=True,
        )


class UsbConnection:
    """Brother QL over USB (pyusb) with ESC i S bulk-transfer status query."""

    def __init__(self, identifier: str, model: str = "QL-820NWB"):
        self.identifier = identifier
        self.model      = model

    def _get_device(self):
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

    def send_job(self, instructions: bytes) -> dict:
        device = self._get_device()
        if device is None:
            raise RuntimeError("USB printer not found")
        try:
            return send(
                instructions=instructions,
                printer_identifier=device,
                backend_identifier="pyusb",
                blocking=True,
            )
        except Exception as exc:
            if getattr(exc, 'errno', None) == 13:
                raise RuntimeError("Printer busy — exit the LCD menu and try again") from exc
            raise
