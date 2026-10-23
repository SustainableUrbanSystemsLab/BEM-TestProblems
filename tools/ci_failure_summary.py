"""Publish short pytest failure annotations, without uploading test artifacts."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def annotate(path):
    if not path.is_file():
        return
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        failures = list(case.findall("failure")) + list(case.findall("error"))
        for failure in failures:
            message = case.attrib.get("name", "test") + ": " + failure.attrib.get("message", "")
            message = message[:6000].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print("::error::" + message, flush=True)


if __name__ == "__main__":
    annotate(Path(sys.argv[1]))
