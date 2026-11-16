# -*- coding: utf-8 -*-
"""Run the forensic review and print a short summary."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hwwatch import config, forensics, store


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    db = store.Store(config.db_path())
    try:
        result, path = forensics.run(db, days=days)
    finally:
        db.close()
    focus = result["focus"]
    print("events:", len(result["rows"]), "days:", days)
    print("xvdd:", len(focus["xvdd"]), "wudf:", len(focus["wudf"]),
          "phantom:", len(focus["phantom"]), "display:", len(focus["display"]),
          "usb:", len(focus["usb"]))
    print("boots:", len(result["boots"]))
    print("inf:", len(result["infs"]), "services:", len(result["services"]),
          "programs:", len(result["programs"]), "tasks matched:", len(result["tasks"]),
          "problems:", len(result["problems"]))
    for hyp in result["hypotheses"]:
        print("[%s] %s -> %s" % (hyp["level"], hyp["title"], hyp["confidence"]))
    print("report:", path)


if __name__ == "__main__":
    main()
