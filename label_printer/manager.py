"""PrinterManager: probes connections, tracks state, broadcasts SSE on change."""

import asyncio
import logging
from typing import Optional

import events as sse
from label_printer.connections import WifiConnection, UsbConnection, find_usb_printer

logger = logging.getLogger("printer")

_FALLBACK_LABEL = "62"
_FALLBACK_W, _FALLBACK_H = 696, 1044


def _label_dims(label_id: str) -> tuple[int, int]:
    from brother_ql.labels import LabelsManager
    lm  = LabelsManager()
    lbl = next((el for el in lm.iter_elements() if el.identifier == label_id), None)
    if lbl is None:
        return _FALLBACK_W, _FALLBACK_H
    w, h = lbl.dots_printable
    return w, (h if h > 0 else _FALLBACK_H)


def _detect_label(status: dict) -> str:
    width  = status.get("media_width", 0)
    length = status.get("media_length", 0)
    if not width:
        return _FALLBACK_LABEL
    try:
        from brother_ql.labels import LabelsManager
        lm = LabelsManager()
        for lbl in lm.iter_elements():
            ts = getattr(lbl, "tape_size", None)
            if ts is None:
                continue
            tw, tl = ts
            if length == 0 and tl == 0 and tw == width:
                return lbl.identifier
            if length > 0 and tw == width and tl == length:
                return lbl.identifier
    except Exception:
        pass
    return _FALLBACK_LABEL


class PrinterManager:
    def __init__(self, wifi_ip: str, model: str = "QL-820NWB"):
        self._wifi_ip   = wifi_ip
        self._model     = model
        self._active    = "wifi"
        self._usb_id: Optional[str] = None
        self._last_label = _FALLBACK_LABEL
        self._last_w, self._last_h = _FALLBACK_W, _FALLBACK_H
        self._state: dict = {
            "connected":   False,
            "active_mode": "wifi",
            "model":       model,
            "label_id":    _FALLBACK_LABEL,
            "label_w":     _FALLBACK_W,
            "label_h":     _FALLBACK_H,
            "media_w_mm":  0,
            "media_h_mm":  0,
            "status":      "checking",
            "errors":      [],
            "wifi": {"connected": False, "ip": wifi_ip},
            "usb":  {"connected": False, "device": None},
        }
        sse.register_init_hook(self._init_payload)

    def _init_payload(self) -> dict:
        return {"printer": self._state}

    def get_state(self) -> dict:
        return self._state

    def set_active(self, mode: str):
        self._active = mode
        self._state = {**self._state, "active_mode": mode, "status": "checking", "errors": []}
        sse.broadcast({"printer": self._state})

    def set_wifi_ip(self, ip: str):
        self._wifi_ip = ip

    async def run(self):
        while True:
            try:
                usb_id       = await asyncio.to_thread(find_usb_printer)
                self._usb_id = usb_id

                if self._active == "usb" and usb_id:
                    conn = UsbConnection(usb_id, self._model)
                else:
                    conn = WifiConnection(self._wifi_ip, self._model)

                result    = await asyncio.to_thread(conn.query_status)
                connected = result["connected"]

                # Auto-fallback: WiFi unreachable but USB is present → switch to USB
                if not connected and self._active == "wifi" and usb_id:
                    conn      = UsbConnection(usb_id, self._model)
                    result    = await asyncio.to_thread(conn.query_status)
                    connected = result["connected"]
                    if connected:
                        self._active = "usb"

                st = result.get("status") or {}

                if st.get("media_width"):
                    label_id = _detect_label(st)
                    w, h     = _label_dims(label_id)
                    self._last_label           = label_id
                    self._last_w, self._last_h = w, h
                else:
                    label_id = self._last_label
                    w, h     = self._last_w, self._last_h

                errors = st.get("errors", [])
                if not connected:
                    pill = "offline"
                elif errors:
                    pill = "error"
                elif "print" in (st.get("phase_type") or "").lower():
                    pill = "printing"
                else:
                    pill = "online"

                new_state = {
                    "connected":   connected,
                    "active_mode": self._active,
                    "model":       self._model,
                    "label_id":    label_id,
                    "label_w":     w,
                    "label_h":     h,
                    "media_w_mm":  st.get("media_width", 0),
                    "media_h_mm":  st.get("media_length", 0),
                    "status":      pill,
                    "errors":      errors,
                    "wifi": {"connected": self._active == "wifi" and connected, "ip": self._wifi_ip},
                    "usb":  {"connected": self._active == "usb"  and connected, "device": usb_id},
                }

                if new_state != self._state:
                    self._state = new_state
                    logger.warning("printer: %s via %s (%s)", pill, self._active,
                                usb_id if self._active == "usb" else self._wifi_ip)
                    sse.broadcast({"printer": new_state})

                await asyncio.sleep(1.0 if connected else 2.0)
            except Exception:
                logger.exception("printer monitor tick failed")
                error_state = {**self._state, "connected": False, "status": "offline"}
                if error_state != self._state:
                    self._state = error_state
                    sse.broadcast({"printer": error_state})
                await asyncio.sleep(2.0)

    def send_job(self, instructions: bytes) -> dict:
        if self._active == "usb" and self._usb_id:
            return UsbConnection(self._usb_id, self._model).send_job(instructions)
        try:
            return WifiConnection(self._wifi_ip, self._model).send_job(instructions)
        except Exception:
            if self._usb_id:
                return UsbConnection(self._usb_id, self._model).send_job(instructions)
            raise
