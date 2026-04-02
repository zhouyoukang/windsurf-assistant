#!/usr/bin/env python3
"""
Windsurf Rate Limit Bypass Patch v3.0 — 上善若水
=============================================
Patches workbench.desktop.main.js to bypass ALL rate limit, quota, and UI blocks.

v3.0 Changes (2026-03-21):
  - P12 added: chatQuotaExceeded/completionsQuotaExceeded context key neutralizer
  - P13 added: quota_exhausted notification/status bar suppressor
  - P14 added: exceeded event suppressor (percentRemaining===0 detection)
  - 水入万物: 消除所有用户可感知的中断点

v2.0 Changes (2026-03-21):
  - P6/P7 removed: already native if(!1) dead code in Windsurf v1.108.2+
  - P8 updated: variable names _u→O1, Hb→qb, xGt→JGt, TGt→KGt
  - P9 updated: function name Qve→fO
  - P11 added: YBe quota exhausted gRPC neutralizer
  - Fixed: product.json UTF-8 BOM reading

Patches:
  P8:  Input Blocker Bypass - INSUFFICIENT_CASCADE_CREDITS no longer blocks
  P9:  gRPC Credit Error Neutralizer - fO()→!1
  P10: Quota Exhaustion Bypass - DVe()→!1
  P11: Quota Exhausted gRPC Neutralizer - YBe()→!1
  P12: Context Key Neutralizer - chatQuotaExceeded/completionsQuotaExceeded never true
  P13: Quota Notification Suppressor - status bar quota_exhausted banner hidden
  P14: Exceeded Event Suppressor - percentRemaining===0 detection disabled

Usage:
  python patch_rate_limit_bypass.py status   # Check current patch status
  python patch_rate_limit_bypass.py apply    # Apply all patches (水入万物)
  python patch_rate_limit_bypass.py revert   # Revert to backup
"""

import sys
import os
import shutil
import hashlib
import base64
import json
import re
from datetime import datetime

WINDSURF_DIR = r"D:\Windsurf"
WORKBENCH_PATH = os.path.join(WINDSURF_DIR, "resources", "app", "out", "vs", "workbench", "workbench.desktop.main.js")
PRODUCT_JSON = os.path.join(WINDSURF_DIR, "resources", "app", "product.json")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "_windsurf_backups")

PATCHES = {
    "P8_INPUT_BLOCKER": {
        "name": "Input Blocker Bypass (Layer 1)",
        "description": "INSUFFICIENT_CASCADE_CREDITS error no longer blocks input",
        "find": 'if(O1){if(re?.code)switch(re.code){case qb.WRITE_CHAT_INSUFFICIENT_CASCADE_CREDITS:et(JGt());break;case qb.WRITE_CHAT_UPGRADE_FOR_CREDITS:et(KGt())}return!1}',
        "replace": 'if(!1){if(re?.code)switch(re.code){case qb.WRITE_CHAT_INSUFFICIENT_CASCADE_CREDITS:et(JGt());break;case qb.WRITE_CHAT_UPGRADE_FOR_CREDITS:et(KGt())}return!1}',
    },
    "P9_GRPC_CREDIT_ERROR": {
        "name": "gRPC Credit Error Neutralizer (Layer 3)",
        "description": "fO() — PermissionDenied errors (billing/acu/payment) no longer trigger credit block UI",
        "find": 'fO=(Z,B)=>Z?!!(Z.errorCode===ct.Cy.PermissionDenied&&Z.userErrorMessage.toLowerCase().includes(B)):!1',
        "replace": 'fO=(Z,B)=>!1',
    },
    "P10_QUOTA_EXHAUSTION": {
        "name": "Quota Exhaustion Bypass (QUOTA billing root)",
        "description": "DVe() never reports quota exhausted — daily/weekly quota checks always pass",
        "find": 'DVe=Z=>vpe(Z)<=0',
        "replace": 'DVe=Z=>!1',
    },
    "P11_QUOTA_EXHAUSTED_GRPC": {
        "name": "Quota Exhausted gRPC Neutralizer",
        "description": "YBe() — ResourceExhausted 'quota exhausted' gRPC error never triggers block UI",
        "find": 'YBe=Z=>((B,j)=>B?!!(B.errorCode===ct.Cy.ResourceExhausted&&B.userErrorMessage.toLowerCase().includes(j)):!1)(Z,"quota exhausted")',
        "replace": 'YBe=Z=>!1',
    },
    "P12_CONTEXT_KEY_NEUTRALIZER": {
        "name": "Context Key Neutralizer (chatQuotaExceeded/completionsQuotaExceeded)",
        "description": "Context keys never set to true — chat input never disabled by quota",
        "find": 'this.m.set(this.j.chat?.percentRemaining===0),this.n.set(this.j.completions?.percentRemaining===0)',
        "replace": 'this.m.set(!1),this.n.set(!1)',
    },
    "P13_QUOTA_NOTIFICATION_SUPPRESSOR": {
        "name": "Quota Notification Suppressor",
        "description": "quota_exhausted status bar notification never shown",
        "find": 'pe==="quota_exhausted"||pe==="quota_exhausted_with_overage"||Wt?.planInfo&&AF(Wt.planInfo)&&DVe(Wt)',
        "replace": '!1||!1||Wt?.planInfo&&AF(Wt.planInfo)&&DVe(Wt)',
    },
    "P14_EXCEEDED_EVENT_SUPPRESSOR": {
        "name": "Exceeded Event Suppressor",
        "description": "percentRemaining===0 transition never fires exceeded event",
        "find": 'exceeded:_?.percentRemaining===0!=(C?.percentRemaining===0)',
        "replace": 'exceeded:!1',
    },
}


def compute_checksum(filepath):
    """Compute SHA-256 checksum in base64 (VS Code format)."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii").rstrip("=")


def backup_file(filepath):
    """Create timestamped backup."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(filepath)
    backup_path = os.path.join(BACKUP_DIR, f"{name}.{ts}.bak")
    shutil.copy2(filepath, backup_path)
    return backup_path


def check_status():
    """Check current patch status."""
    if not os.path.exists(WORKBENCH_PATH):
        print(f"ERROR: Workbench not found at {WORKBENCH_PATH}")
        return False

    with open(WORKBENCH_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"Windsurf: {WINDSURF_DIR}")
    print(f"Workbench: {WORKBENCH_PATH}")
    print(f"File size: {len(content):,} chars")
    print()

    all_applied = True
    for pid, patch in PATCHES.items():
        has_original = patch["find"] in content
        # For patches where find != replace, check if replace string exists
        if patch["find"] != patch["replace"]:
            has_patched = patch["replace"] in content
        else:
            has_patched = False

        if has_patched and not has_original:
            status = "APPLIED"
        elif has_patched and has_original:
            # Both exist (unlikely but possible if replace is substring of find)
            status = "APPLIED"
        elif has_original:
            status = "NOT APPLIED"
            all_applied = False
        else:
            status = "NOT FOUND (code changed?)"
            all_applied = False

        print(f"  {pid} ({patch['name']}): {status}")

    print()

    # Check product.json checksum
    current_checksum = compute_checksum(WORKBENCH_PATH)
    with open(PRODUCT_JSON, "r", encoding="utf-8-sig") as f:
        product = json.load(f)

    stored_checksum = product.get("checksums", {}).get(
        "vs/workbench/workbench.desktop.main.js", ""
    )

    checksum_match = current_checksum == stored_checksum
    print(f"  Checksum match: {'YES' if checksum_match else 'NO (will show corrupt warning)'}")
    print(f"    Current:  {current_checksum}")
    print(f"    Stored:   {stored_checksum}")

    return all_applied


def apply_patches():
    """Apply all patches."""
    if not os.path.exists(WORKBENCH_PATH):
        print(f"ERROR: Workbench not found at {WORKBENCH_PATH}")
        return False

    # Backup
    backup = backup_file(WORKBENCH_PATH)
    product_backup = backup_file(PRODUCT_JSON)
    print(f"Backup: {backup}")
    print(f"Product backup: {product_backup}")

    with open(WORKBENCH_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    applied = 0
    for pid, patch in PATCHES.items():
        if patch["replace"] in content:
            print(f"  {pid}: Already applied, skipping")
            applied += 1
            continue

        if patch["find"] not in content:
            print(f"  {pid}: NOT FOUND - code may have changed")
            continue

        content = content.replace(patch["find"], patch["replace"], 1)
        print(f"  {pid}: APPLIED - {patch['description']}")
        applied += 1

    # Write patched workbench
    with open(WORKBENCH_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    # Update checksum in product.json
    new_checksum = compute_checksum(WORKBENCH_PATH)
    with open(PRODUCT_JSON, "r", encoding="utf-8-sig") as f:
        product = json.load(f)

    if "checksums" in product:
        product["checksums"]["vs/workbench/workbench.desktop.main.js"] = new_checksum

    with open(PRODUCT_JSON, "w", encoding="utf-8") as f:
        json.dump(product, f, indent="\t")

    print(f"\n  Checksum updated: {new_checksum}")
    print(f"\n  {applied}/{len(PATCHES)} patches applied")
    print(f"\n  RESTART Windsurf to activate patches")

    return applied == len(PATCHES)


def revert():
    """Revert to most recent backup."""
    if not os.path.exists(BACKUP_DIR):
        print("No backups found")
        return False

    # Find most recent workbench backup
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("workbench") and f.endswith(".bak")],
        reverse=True,
    )

    if not backups:
        print("No workbench backups found")
        return False

    backup_path = os.path.join(BACKUP_DIR, backups[0])
    shutil.copy2(backup_path, WORKBENCH_PATH)
    print(f"Reverted workbench from: {backups[0]}")

    # Revert product.json
    product_backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("product") and f.endswith(".bak")],
        reverse=True,
    )

    if product_backups:
        product_backup = os.path.join(BACKUP_DIR, product_backups[0])
        shutil.copy2(product_backup, PRODUCT_JSON)
        print(f"Reverted product.json from: {product_backups[0]}")

    # Update checksum
    new_checksum = compute_checksum(WORKBENCH_PATH)
    with open(PRODUCT_JSON, "r", encoding="utf-8-sig") as f:
        product = json.load(f)
    if "checksums" in product:
        product["checksums"]["vs/workbench/workbench.desktop.main.js"] = new_checksum
    with open(PRODUCT_JSON, "w", encoding="utf-8") as f:
        json.dump(product, f, indent="\t")

    print(f"Checksum updated: {new_checksum}")
    print("RESTART Windsurf to activate revert")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python patch_rate_limit_bypass.py [status|apply|revert]")
        return

    cmd = sys.argv[1].lower()
    if cmd == "status":
        check_status()
    elif cmd == "apply":
        apply_patches()
    elif cmd == "revert":
        revert()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
