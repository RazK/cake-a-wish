"""WiFi and USB connection implementations for Brother QL label printers."""

import re
import socket
import sys
import urllib.request
import logging
from typing import Optional

from brother_ql.backends.helpers import discover, send
from brother_ql.reader import interpret_response

if sys.platform == "win32":
    try:
        import win32print as _win32print
    except ImportError:
        _win32print = None

# Logger for printer connection helpers
logger = logging.getLogger("printer.conn")

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
_BROTHER_KEYWORDS = ("brother", "ql-")

# Win32 printer flags (used when win32print is available).
# The spooler never sets PRINTER_STATUS_OFFLINE (0x80) for USB printers that are
# physically unplugged — it only sets PRINTER_ATTRIBUTE_WORK_OFFLINE (0x400) in
# the Attributes field.  We check both so either path is caught.
PRINTER_STATUS_OFFLINE        = 0x00000080
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400


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
    """Return a USB printer identifier for the current platform, or None."""
    if sys.platform == "win32":
        if _win32print is None:
            return None
        try:
            names = []
            for _, _, name, _ in _win32print.EnumPrinters(_win32print.PRINTER_ENUM_LOCAL):
                names.append(name)
                if any(kw in name.lower() for kw in _BROTHER_KEYWORDS):
                    logger.debug("find_usb_printer: found candidate printer '%s'", name)
                    return name
            logger.debug("find_usb_printer: installed printers: %s", names)
        except Exception:
            pass
        return None
    try:
        devices = discover('pyusb')
        return devices[0]['identifier'] if devices else None
    except Exception:
        return None


def make_usb_conn(usb_id: str, model: str = "QL-820NWB"):
    """Return the right USB connection class for the current platform."""
    if sys.platform == "win32":
        return WinUsbConnection(usb_id, model)
    return LinuxUsbConnection(usb_id, model)


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


class LinuxUsbConnection:
    """Brother QL over USB via pyusb (Mac / Linux)."""

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


class WinUsbConnection:
    """Brother QL over Windows print spooler RAW port (win32print).

    Works with the Brother driver Windows already has — no Zadig, no admin step.
    Status is presence-only (no ESC i S via spooler).
    """

    def __init__(self, printer_name: str, model: str = "QL-820NWB"):
        self.printer_name = printer_name
        self.model        = model

    def query_status(self) -> dict:
        try:
            h = _win32print.OpenPrinter(self.printer_name)
        except Exception:
            logger.debug("WinUsbConnection.query_status: OpenPrinter failed for '%s'", self.printer_name)
            return {"connected": False, "status": None}
        try:
            try:
                info = _win32print.GetPrinter(h, 2)
            except Exception:
                info = {}
            if not isinstance(info, dict):
                info = {}
            status = info.get('Status', 0)
            attrs  = info.get('Attributes', 0)
            logger.debug("WinUsbConnection.query_status: printer=%s status=%#x attrs=%#x port=%s",
                         self.printer_name, status, attrs, info.get('pPortName'))
            offline = (status & PRINTER_STATUS_OFFLINE) or (attrs & PRINTER_ATTRIBUTE_WORK_OFFLINE)
            return {"connected": not offline, "status": None}
        finally:
            try:
                _win32print.ClosePrinter(h)
            except Exception:
                pass

    def send_job(self, instructions: bytes) -> dict:
        try:
            h = _win32print.OpenPrinter(self.printer_name)
        except Exception as exc:
            raise RuntimeError(f"Cannot open printer '{self.printer_name}'") from exc
        doc_started = False
        try:
            _win32print.StartDocPrinter(h, 1, ("label", None, "RAW"))
            doc_started = True
            _win32print.StartPagePrinter(h)
            _win32print.WritePrinter(h, instructions)
            _win32print.EndPagePrinter(h)
            _win32print.EndDocPrinter(h)
            doc_started = False
        finally:
            if doc_started:
                try:
                    _win32print.EndDocPrinter(h)
                except Exception:
                    pass
            _win32print.ClosePrinter(h)
        return {"did_print": True}
