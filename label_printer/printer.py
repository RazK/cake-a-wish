import re
import ssl
from typing import Optional
from urllib.request import (
    build_opener,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPBasicAuthHandler,
    HTTPSHandler,
    HTTPHandler,
)

from brother_ql.backends.helpers import send
from brother_ql.labels import LabelsManager


class BrotherPrinter:
    def __init__(self, ip: str, model: str = "QL-820NWB", password: Optional[str] = None):
        self.ip = ip
        self.model = model
        self.password = password

    def _open_url(self, url: str) -> Optional[str]:
        try:
            pm = HTTPPasswordMgrWithDefaultRealm()
            if self.password:
                pm.add_password(None, url, "admin", self.password)
                handler = HTTPBasicAuthHandler(pm)
                opener = build_opener(handler, HTTPSHandler(context=ssl._create_unverified_context()), HTTPHandler())
            else:
                opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()), HTTPHandler())
            return opener.open(url, timeout=5).read().decode("utf-8", errors="ignore")
        except Exception:
            return None

    def detect_label(self) -> Optional[str]:
        """Read the printer web UI and return a brother_ql label id if found."""
        urls = [f"https://{self.ip}/home/status.html", f"http://{self.ip}/home/status.html", f"https://{self.ip}/", f"http://{self.ip}/"]
        lm = LabelsManager()
        ids = list(lm.iter_identifiers())
        for url in urls:
            data = self._open_url(url)
            if not data:
                continue
            m = re.search(r"([0-9]{1,3})\s*mm\s*[x×]\s*([0-9]{1,3})\s*mm", data, re.I)
            if m:
                w, h = int(m.group(1)), int(m.group(2))
                candidate = f"{w}x{h}"
                if candidate in ids:
                    return candidate
                rev = f"{h}x{w}"
                if rev in ids:
                    return rev
            m2 = re.search(r"([0-9]{1,3})\s*mm\s*(endless|continuous|roll)", data, re.I)
            if m2:
                w = int(m2.group(1))
                candidate = str(w)
                if candidate in ids:
                    return candidate
        return None

    def send_instructions(self, instructions: bytes) -> dict:
        return send(instructions=instructions, printer_identifier=f"tcp://{self.ip}", backend_identifier="network", blocking=True)
