"""000-本源_Origin · 锚.py
===================================================================
为道日损 · 无为而无不为 · 少改动少破坏

Windsurf LS 真正读取的 API URL 存在 state.vscdb 的 secret 条目:
  key = secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}
  value = Electron safeStorage 加密 blob (v10 + nonce + AES-GCM(master_key))

master_key 存在 %APPDATA%\\Windsurf\\Local State 的 os_crypt.encrypted_key
(DPAPI 前缀 + 加密 32 字节 key)

CLI:
  python 锚.py read                  - 解密并打印当前 apiServerUrl
  python 锚.py anchor [URL]          - 备份 + 加密新 URL + 写回
                                       默认 URL = http://127.0.0.1:8889
  python 锚.py restore               - 从备份还原
  python 锚.py status                - 打印锚定状态 (是否指向本源反代)

备份: _anchor_backup.json (创建后不会被 anchor 覆盖; 要重新备份先 restore)

约束:
  - 只动 apiServerUrl, 不动 sessions/accessToken
  - Windsurf LS 重启 (Reload Window) 前不会生效, 对当前对话零干扰
  - 所有操作可完全还原
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import pathlib
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("ERROR: need 'cryptography' package. install: pip install cryptography")
    sys.exit(2)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = pathlib.Path(__file__).parent
BACKUP_FILE = SCRIPT_DIR / "_anchor_backup.json"

APPDATA = pathlib.Path(os.environ["APPDATA"])
DEFAULT_DB_PATH = APPDATA / "Windsurf/User/globalStorage/state.vscdb"
DEFAULT_LOCAL_STATE = APPDATA / "Windsurf/Local State"
# 运行期可通过 CLI 参数覆写; 默认指向真实 Windsurf 数据目录
DB_PATH = DEFAULT_DB_PATH
LOCAL_STATE = DEFAULT_LOCAL_STATE

SECRET_KEY_APIURL = (
    'secret://{"extensionId":"codeium.windsurf",'
    '"key":"windsurf_auth.apiServerUrl"}'
)

DEFAULT_ANCHOR = "http://127.0.0.1:8889"
CLOUD_ORIGIN = "https://server.self-serve.windsurf.com"


# ─────────────────────────────────────────────────────────────────
# DPAPI + AES-GCM (Electron safeStorage 方案)
# ─────────────────────────────────────────────────────────────────
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def dpapi_decrypt(encrypted: bytes) -> bytes | None:
    blob_in = _DATA_BLOB()
    blob_in.cbData = len(encrypted)
    blob_in.pbData = (ctypes.c_byte * len(encrypted))(*encrypted)
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        return None
    cb, pb = blob_out.cbData, blob_out.pbData
    if not pb or cb == 0:
        return b""
    out = ctypes.string_at(pb, cb)
    ctypes.windll.kernel32.LocalFree(pb)
    return out


def load_master_key() -> bytes:
    if not LOCAL_STATE.exists():
        raise FileNotFoundError(f"not found: {LOCAL_STATE}")
    data = json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    encrypted_key_b64 = data["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)
    if encrypted_key[:5] != b"DPAPI":
        raise ValueError(f"unexpected prefix: {encrypted_key[:5]!r}")
    mk = dpapi_decrypt(encrypted_key[5:])
    if not mk or len(mk) != 32:
        raise RuntimeError("master key decrypt failed / wrong length")
    return mk


def decrypt_v10(master_key: bytes, blob: bytes) -> bytes:
    if blob[:3] != b"v10":
        raise ValueError(f"expected v10 prefix, got {blob[:3]!r}")
    nonce = blob[3:15]
    ct = blob[15:]
    return AESGCM(master_key).decrypt(nonce, ct, None)


def encrypt_v10(master_key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(master_key).encrypt(nonce, plaintext, None)
    return b"v10" + nonce + ct


# ─────────────────────────────────────────────────────────────────
# state.vscdb 读/写 (带 writer 锁等待)
# ─────────────────────────────────────────────────────────────────
def db_read_blob(key: str) -> bytes | None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        val = json.loads(row[0])
        return bytes(val["data"])
    finally:
        conn.close()


def db_write_blob(key: str, blob: bytes, retries: int = 10) -> None:
    """写入 blob, 自动重试以避开 LS 的 WAL 锁."""
    payload = json.dumps({"type": "Buffer", "data": list(blob)})
    last_err = None
    for i in range(retries):
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
            try:
                conn.execute(
                    "UPDATE ItemTable SET value = ? WHERE key = ?",
                    (payload, key),
                )
                if conn.total_changes == 0:
                    # row 不存在 → INSERT
                    conn.execute(
                        "INSERT INTO ItemTable(key, value) VALUES(?, ?)",
                        (key, payload),
                    )
                conn.commit()
                return
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            time.sleep(0.3 * (i + 1))
    raise RuntimeError(f"db write failed after {retries} retries: {last_err}")


# ─────────────────────────────────────────────────────────────────
# 业务操作
# ─────────────────────────────────────────────────────────────────
def op_read() -> str:
    mk = load_master_key()
    raw = db_read_blob(SECRET_KEY_APIURL)
    if raw is None:
        print("(no such secret row)")
        return ""
    pt = decrypt_v10(mk, raw).decode("utf-8", errors="replace")
    print(f"current apiServerUrl = {pt!r}")
    return pt


def op_status() -> None:
    try:
        cur = op_read()
    except Exception as e:
        print(f"read failed: {e}")
        return
    anchored = cur.startswith("http://127.0.0.1:") or cur.startswith(
        "http://localhost:"
    )
    backup_exists = BACKUP_FILE.exists()
    print()
    print(f"锚定状态:  {'已锚定本源反代' if anchored else '指向官方云 (未锚定)'}")
    print(f"备份文件:  {'存在' if backup_exists else '不存在'} ({BACKUP_FILE.name})")
    if backup_exists:
        try:
            b = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
            print(f"  备份原URL: {b.get('original_url')}")
            print(f"  备份时间:  {b.get('anchored_at')}")
        except Exception as e:
            print(f"  (备份文件解析失败: {e})")


def op_anchor(new_url: str) -> None:
    mk = load_master_key()
    # 1) 读原始 blob (只有一份原始值, 不应被覆盖的备份)
    raw = db_read_blob(SECRET_KEY_APIURL)
    if raw is None:
        print("WARN: apiServerUrl secret 不存在, 将创建新条目")
        orig_url = ""
    else:
        orig_url = decrypt_v10(mk, raw).decode("utf-8", errors="replace")
    # 2) 保护: 如果 orig_url 已是本地反代, 拒绝二次锚定 (避免覆盖真正的备份)
    if orig_url.startswith("http://127.0.0.1:") or orig_url.startswith(
        "http://localhost:"
    ):
        if BACKUP_FILE.exists():
            print(
                "已处于锚定状态, 且备份存在. 如需更换反代 URL, 请先 restore.\n"
                f"(当前: {orig_url} → 欲改: {new_url})"
            )
            return
        print(
            "WARN: 当前 URL 已是本地反代, 但无备份. 将覆盖为新 URL (无法还原到真实云端)."
        )
    # 3) 写备份 (如果已有备份且 orig 非本地, 更新备份内的 blob)
    if not BACKUP_FILE.exists() or not (
        orig_url.startswith("http://127.0.0.1:")
        or orig_url.startswith("http://localhost:")
    ):
        BACKUP_FILE.write_text(
            json.dumps(
                {
                    "original_url": orig_url,
                    "original_blob_hex": raw.hex() if raw else None,
                    "anchored_at": datetime.now(timezone.utc).isoformat(),
                    "new_url": new_url,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"备份 → {BACKUP_FILE}")
    # 4) 加密新 URL + 写回
    new_blob = encrypt_v10(mk, new_url.encode("utf-8"))
    db_write_blob(SECRET_KEY_APIURL, new_blob)
    # 5) 同时把 ItemTable 的明文 apiServerUrl 字段 (如果存在) 也改成新 URL,
    #    避免某些代码路径读这份
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
        conn.execute(
            "UPDATE ItemTable SET value = ? WHERE key = ?",
            (json.dumps(new_url), "apiServerUrl"),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"(ItemTable.apiServerUrl 同步失败, 可忽略: {e})")
    # 6) 验证
    reread = decrypt_v10(mk, db_read_blob(SECRET_KEY_APIURL)).decode("utf-8")
    assert reread == new_url, f"verify failed: {reread!r} != {new_url!r}"
    print(f"锚定 ✓  secret://apiServerUrl = {new_url}")
    print(f"原 URL = {orig_url}")
    print("下一步: 在 Windsurf 按 Ctrl+Shift+P → Reload Window 生效")


def op_restore() -> None:
    if not BACKUP_FILE.exists():
        print(f"no backup: {BACKUP_FILE}")
        sys.exit(1)
    b = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
    orig_url = b.get("original_url", "")
    orig_blob_hex = b.get("original_blob_hex")
    mk = load_master_key()
    # 优先用原始 blob 精确还原 (保留原 nonce); 如果没有, 则用 orig_url 重加密
    if orig_blob_hex:
        blob = bytes.fromhex(orig_blob_hex)
        # 验证能正常解密
        try:
            decrypt_v10(mk, blob)
            db_write_blob(SECRET_KEY_APIURL, blob)
            print(f"从原始 blob 精确还原 ✓")
        except Exception as e:
            print(f"原始 blob 解密失败 ({e}), 改用 orig_url 重加密")
            db_write_blob(SECRET_KEY_APIURL, encrypt_v10(mk, orig_url.encode("utf-8")))
    elif orig_url:
        db_write_blob(SECRET_KEY_APIURL, encrypt_v10(mk, orig_url.encode("utf-8")))
        print(f"用 orig_url 重加密还原 ✓")
    else:
        print("ERROR: 备份中既无 orig_blob_hex 也无 original_url")
        sys.exit(1)
    # ItemTable 明文也还原
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
        conn.execute(
            "UPDATE ItemTable SET value = ? WHERE key = ?",
            (json.dumps(orig_url), "apiServerUrl"),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"(ItemTable.apiServerUrl 同步失败, 可忽略: {e})")
    # 删备份
    BACKUP_FILE.rename(
        BACKUP_FILE.with_name(
            BACKUP_FILE.stem
            + "_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
    )
    # 验证
    reread = decrypt_v10(mk, db_read_blob(SECRET_KEY_APIURL)).decode("utf-8")
    print(f"还原 ✓  secret://apiServerUrl = {reread}")
    print("下一步: 在 Windsurf 按 Ctrl+Shift+P → Reload Window 生效")


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
# settings.json 侧锚点 (codeium.inferenceApiServerUrl)
# LS 子进程的 --inference_api_server_url 来自这里
# ─────────────────────────────────────────────────────────────────
SETTINGS_JSON = APPDATA / "Windsurf/User/settings.json"
SETTINGS_BACKUP = SCRIPT_DIR / "_settings_backup.json"
INFERENCE_KEY = "codeium.inferenceApiServerUrl"
DEFAULT_INFERENCE_ANCHOR = "http://127.0.0.1:8889/i"


def _load_settings() -> dict:
    if not SETTINGS_JSON.exists():
        return {}
    try:
        return json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARN: settings.json 解析失败: {e}"); return {}


def _save_settings(obj: dict) -> None:
    SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_JSON.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def op_read_inference() -> None:
    s = _load_settings()
    cur = s.get(INFERENCE_KEY)
    if cur is None:
        print(f"{INFERENCE_KEY} = <未设置> (LS 将用默认 https://inference.codeium.com)")
    else:
        print(f"{INFERENCE_KEY} = {cur!r}")


def op_anchor_inference(new_url: str) -> None:
    s = _load_settings()
    orig = s.get(INFERENCE_KEY)  # 可能 None
    # 写备份 (只记第一次; 后续 anchor 不覆盖)
    if not SETTINGS_BACKUP.exists():
        SETTINGS_BACKUP.write_text(
            json.dumps(
                {"key": INFERENCE_KEY, "original": orig, "settings_file": str(SETTINGS_JSON)},
                indent=2, ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"备份 → {SETTINGS_BACKUP}")
    s[INFERENCE_KEY] = new_url
    _save_settings(s)
    print(f"锚定 ✓  {INFERENCE_KEY} = {new_url}")
    if orig is None:
        print("  (原 key 不存在, 回滚时会删除此 key)")
    else:
        print(f"  原值 = {orig!r}")


def op_restore_inference() -> None:
    if not SETTINGS_BACKUP.exists():
        print(f"无备份, 跳过 (没做过 inference 锚定?): {SETTINGS_BACKUP}")
        return
    bk = json.loads(SETTINGS_BACKUP.read_text(encoding="utf-8"))
    s = _load_settings()
    orig = bk.get("original")
    if orig is None:
        s.pop(INFERENCE_KEY, None)
    else:
        s[INFERENCE_KEY] = orig
    _save_settings(s)
    # 归档备份
    SETTINGS_BACKUP.rename(
        SETTINGS_BACKUP.with_name(
            f"_settings_backup_restored_{datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
    )
    print(f"还原 ✓  {INFERENCE_KEY} = {orig!r}")


# ─────────────────────────────────────────────────────────────────
# codeium.windsurf globalState (VS Code ExtensionContext.globalState)
# Extension via getApiServerUrlFromContext() 会 fallback 到
#   A.globalState.get("apiServerUrl") / .get("inferenceApiServerUrl")
# 当用户设置 (codeium.apiServerUrl) 因 dev-mode gate 被忽略时,
# 这是 production 用户实际生效的 URL 源.
# 存在 state.vscdb ItemTable key='codeium.windsurf' 的 JSON blob 里.
# ─────────────────────────────────────────────────────────────────
GLOBALSTATE_KEY = "codeium.windsurf"
GLOBALSTATE_BACKUP = SCRIPT_DIR / "_globalstate_backup.json"


def _read_globalstate_blob() -> dict | None:
    """读 codeium.windsurf globalState JSON blob (7MB). 返回解析后的 dict."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (GLOBALSTATE_KEY,)
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])
    finally:
        conn.close()


def _write_globalstate_blob(obj: dict, retries: int = 10) -> None:
    """写回 codeium.windsurf globalState (紧凑 JSON, 无缩进)."""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    last_err = None
    for i in range(retries):
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
            try:
                conn.execute(
                    "UPDATE ItemTable SET value = ? WHERE key = ?",
                    (payload, GLOBALSTATE_KEY),
                )
                if conn.total_changes == 0:
                    conn.execute(
                        "INSERT INTO ItemTable(key, value) VALUES(?, ?)",
                        (GLOBALSTATE_KEY, payload),
                    )
                conn.commit()
                return
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            time.sleep(0.3 * (i + 1))
    raise RuntimeError(f"globalState write failed: {last_err}")


def op_read_globalstate() -> None:
    obj = _read_globalstate_blob()
    if obj is None:
        print(f"(codeium.windsurf globalState 不存在)")
        return
    cur_mgmt = obj.get("apiServerUrl", "<未设置>")
    cur_infer = obj.get("inferenceApiServerUrl", "<未设置>")
    print(f"globalState.apiServerUrl          = {cur_mgmt!r}")
    print(f"globalState.inferenceApiServerUrl = {cur_infer!r}")


def op_anchor_globalstate(mgmt_url: str, infer_url: str | None = None) -> None:
    """锚定 codeium.windsurf globalState 里的 apiServerUrl + inferenceApiServerUrl"""
    if infer_url is None:
        infer_url = mgmt_url
    obj = _read_globalstate_blob()
    if obj is None:
        print("ERROR: codeium.windsurf globalState 不存在, 无法锚定")
        sys.exit(1)
    orig_mgmt = obj.get("apiServerUrl")
    orig_infer = obj.get("inferenceApiServerUrl")
    # 备份 (仅第一次; 后续保持原始值)
    if not GLOBALSTATE_BACKUP.exists():
        GLOBALSTATE_BACKUP.write_text(
            json.dumps(
                {
                    "db": str(DB_PATH),
                    "original_apiServerUrl": orig_mgmt,
                    "original_inferenceApiServerUrl": orig_infer,
                    "anchored_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"备份 → {GLOBALSTATE_BACKUP}")
    obj["apiServerUrl"] = mgmt_url
    obj["inferenceApiServerUrl"] = infer_url
    _write_globalstate_blob(obj)
    print(f"锚定 ✓  globalState.apiServerUrl          = {mgmt_url}")
    print(f"锚定 ✓  globalState.inferenceApiServerUrl = {infer_url}")
    if orig_mgmt is not None:
        print(f"  原 apiServerUrl          = {orig_mgmt!r}")
    if orig_infer is not None:
        print(f"  原 inferenceApiServerUrl = {orig_infer!r}")


def op_restore_globalstate() -> None:
    if not GLOBALSTATE_BACKUP.exists():
        print(f"无备份, 跳过: {GLOBALSTATE_BACKUP}")
        return
    bk = json.loads(GLOBALSTATE_BACKUP.read_text(encoding="utf-8"))
    obj = _read_globalstate_blob()
    if obj is None:
        print("ERROR: globalState 缺失, 无法还原")
        sys.exit(1)
    orig_mgmt = bk.get("original_apiServerUrl")
    orig_infer = bk.get("original_inferenceApiServerUrl")
    if orig_mgmt is None:
        obj.pop("apiServerUrl", None)
    else:
        obj["apiServerUrl"] = orig_mgmt
    if orig_infer is None:
        obj.pop("inferenceApiServerUrl", None)
    else:
        obj["inferenceApiServerUrl"] = orig_infer
    _write_globalstate_blob(obj)
    GLOBALSTATE_BACKUP.rename(
        GLOBALSTATE_BACKUP.with_name(
            GLOBALSTATE_BACKUP.stem
            + "_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
    )
    print(f"还原 ✓  globalState.apiServerUrl          = {orig_mgmt!r}")
    print(f"还原 ✓  globalState.inferenceApiServerUrl = {orig_infer!r}")


def _parse_path_flags(args: list[str]) -> list[str]:
    """
    从任意参数列表中抽出 --db <path>, --local-state <path>, --settings <path>,
    改写全局 DB_PATH / LOCAL_STATE / SETTINGS_JSON, 返回剩余参数.
    允许在测试中定向到临时 user-data-dir 的副本.
    """
    global DB_PATH, LOCAL_STATE, SETTINGS_JSON
    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--db" and i + 1 < len(args):
            DB_PATH = pathlib.Path(args[i + 1])
            i += 2
            continue
        if a == "--local-state" and i + 1 < len(args):
            LOCAL_STATE = pathlib.Path(args[i + 1])
            i += 2
            continue
        if a == "--settings" and i + 1 < len(args):
            SETTINGS_JSON = pathlib.Path(args[i + 1])
            i += 2
            continue
        out.append(a)
        i += 1
    return out


# ─────────────────────────────────────────────────────────────────
# v17.53.0 · anchor-all-globalstate · 一网打尽 · 道法自然
# 以数定取 · 不以名定取 · 其数一也
#   识取条件: ItemTable value 为 JSON dict 且含 apiServerUrl-like 字段
#   旧版以 KNOWN_STORE_HINTS 名单硬过滤 → 新 publisher 必漏
#   新版以字段自证 → 任 publisher 若存 apiServerUrl 皆收
#   (已知: codeium.windsurf / dao-agi.windsurf-dao / dao-agi.windsurf-cascade / 未来任何)
# 软适配: DAO_ANCHOR_EXTRA_HINTS (env) 可补白名单 · 保向前兼容
# 每一 blob 被锚时原值入 _multistore_backup.json (为还原计)
# ─────────────────────────────────────────────────────────────────
MULTI_BACKUP_FILE = SCRIPT_DIR / "_multistore_backup.json"

# 可选 allow-list (仅 opt-in · 默认不启用 · 为兼容/调试保留)
# 置 DAO_ANCHOR_STRICT_HINTS=1 可启严格模式 (仅允下列 prefix)
# 置 DAO_ANCHOR_EXTRA_HINTS="foo,bar" 追加 hint
_DEFAULT_KNOWN_HINTS = (
    "windsurf",
    "windsurf-dao",
    "windsurf-cascade",
    "codeium.windsurf",
)


def _get_known_hints() -> tuple[str, ...]:
    extra = os.environ.get("DAO_ANCHOR_EXTRA_HINTS", "").strip()
    extras = tuple(h.strip() for h in extra.split(",") if h.strip()) if extra else ()
    return _DEFAULT_KNOWN_HINTS + extras


def _hint_matches(key: str, hint: str) -> bool:
    """以段 (segment) 为界 · 防 substring 误配
    key='codeium.windsurf'      + hint='windsurf'      → True   (dot-segment 完整)
    key='dao-agi.windsurf-dao'  + hint='windsurf-dao'  → True   (dot-segment 完整)
    key='customfork.mywindsurf' + hint='windsurf'      → False  ('my' 前缀 · 非界段)
    key='codeium.windsurf'      + hint='codeium.windsurf' → True (整键相等)
    """
    if not key or not hint:
        return False
    if key == hint:
        return True
    # 分解为 '.' '-' ':' 连接的段 · 检查是否任一段完整等于 hint
    import re
    segments = re.split(r"[.\-:/]", key)
    if hint in segments:
        return True
    # hint 本身含分隔符 (如 'windsurf-dao') · 视 key 是否出现此完整 token
    if any(sep in hint for sep in (".", "-", ":", "/")):
        return bool(re.search(rf"(^|[.\-:/]){re.escape(hint)}($|[.\-:/])", key))
    return False


# v17.53.0 apiServerUrl-like 字段侦测 · 数据自证
_ANCHOR_FIELD_HINTS = ("apiServer", "inferenceApi", "windsurf_auth")


def _looks_like_anchor_store(obj: dict) -> bool:
    """数据自证: dict 若含 apiServerUrl-like 字段, 即为 anchor-worthy."""
    if not isinstance(obj, dict):
        return False
    for kk in obj.keys():
        if not isinstance(kk, str):
            continue
        if any(h in kk for h in _ANCHOR_FIELD_HINTS):
            return True
    return False


def _enumerate_anchor_stores() -> list[tuple[str, dict]]:
    """返所有含 apiServerUrl-like 字段的 globalState blob: [(key, obj), ...]

    道法自然: 以数 (字段自证) 定取 · 不以名硬过滤
    软适配:   DAO_ANCHOR_STRICT_HINTS=1 启严格模式 (+DAO_ANCHOR_EXTRA_HINTS 可扩)
    """
    strict = os.environ.get("DAO_ANCHOR_STRICT_HINTS", "").strip() in ("1", "true", "yes")
    hints = _get_known_hints() if strict else None
    out: list[tuple[str, dict]] = []
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute("SELECT key, value FROM ItemTable").fetchall()
    finally:
        conn.close()
    for k, v in rows:
        if not isinstance(v, str) or not v.startswith("{"):
            continue
        if hints is not None and not any(_hint_matches(k or "", h) for h in hints):
            continue  # 严格模式: 仅允名单 (段界 match · 防 substring 误配)
        try:
            obj = json.loads(v)
        except Exception:
            continue
        # 数据自证 (宽松模式唯一门 · 严格模式次门)
        if _looks_like_anchor_store(obj):
            out.append((k, obj))
    return out


def op_read_all_globalstate() -> None:
    stores = _enumerate_anchor_stores()
    if not stores:
        print("(no anchor-bearing globalState stores found)")
        return
    print(f"找到 {len(stores)} 个 globalState 存储:")
    for k, obj in stores:
        api = obj.get("apiServerUrl", "<NOT_SET>")
        infer = obj.get("inferenceApiServerUrl", "<NOT_SET>")
        print(f"  § {k}")
        print(f"      apiServerUrl          = {api!r}")
        print(f"      inferenceApiServerUrl = {infer!r}")


def op_anchor_all_globalstate(mgmt_url: str, infer_url: str | None = None) -> None:
    """锚定所有 windsurf 系 globalState 之 apiServerUrl + inferenceApiServerUrl"""
    if infer_url is None:
        infer_url = mgmt_url
    stores = _enumerate_anchor_stores()
    if not stores:
        print("(no anchor-bearing globalState stores found)")
        return
    # 备份 (仅首次 · 后续保持原始)
    if not MULTI_BACKUP_FILE.exists():
        bk = {
            "db": str(DB_PATH),
            "anchored_at": datetime.now(timezone.utc).isoformat(),
            "stores": [
                {
                    "key": k,
                    "original_apiServerUrl": obj.get("apiServerUrl"),
                    "original_inferenceApiServerUrl": obj.get("inferenceApiServerUrl"),
                }
                for k, obj in stores
            ],
        }
        MULTI_BACKUP_FILE.write_text(
            json.dumps(bk, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"备份 → {MULTI_BACKUP_FILE}")
    # 锚
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0)
    try:
        for k, obj in stores:
            orig_api = obj.get("apiServerUrl")
            orig_infer = obj.get("inferenceApiServerUrl")
            obj["apiServerUrl"] = mgmt_url
            obj["inferenceApiServerUrl"] = infer_url
            payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "UPDATE ItemTable SET value = ? WHERE key = ?", (payload, k)
            )
            print(f"锚 ✓ {k}")
            print(f"    api:   {orig_api!r} → {mgmt_url}")
            print(f"    infer: {orig_infer!r} → {infer_url}")
        conn.commit()
    finally:
        conn.close()


def op_restore_all_globalstate() -> None:
    if not MULTI_BACKUP_FILE.exists():
        print(f"无备份, 跳过: {MULTI_BACKUP_FILE}")
        return
    bk = json.loads(MULTI_BACKUP_FILE.read_text(encoding="utf-8"))
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0)
    try:
        for st in bk.get("stores", []):
            k = st["key"]
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?", (k,)
            ).fetchone()
            if not row:
                continue
            try:
                obj = json.loads(row[0])
            except Exception:
                continue
            ori_api = st.get("original_apiServerUrl")
            ori_infer = st.get("original_inferenceApiServerUrl")
            if ori_api is None:
                obj.pop("apiServerUrl", None)
            else:
                obj["apiServerUrl"] = ori_api
            if ori_infer is None:
                obj.pop("inferenceApiServerUrl", None)
            else:
                obj["inferenceApiServerUrl"] = ori_infer
            payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "UPDATE ItemTable SET value = ? WHERE key = ?", (payload, k)
            )
            print(f"还原 ✓ {k}  api={ori_api!r} infer={ori_infer!r}")
        conn.commit()
    finally:
        conn.close()
    MULTI_BACKUP_FILE.rename(
        MULTI_BACKUP_FILE.with_name(
            MULTI_BACKUP_FILE.stem
            + "_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
    )


def main() -> None:
    raw_args = sys.argv[1:]
    rest = _parse_path_flags(raw_args)
    args = rest if rest else ["status"]
    cmd = args[0]
    # inference 分支不依赖 state.vscdb, 在其他命令前先检查
    if cmd == "anchor-inference":
        url = args[1] if len(args) > 1 else DEFAULT_INFERENCE_ANCHOR
        op_anchor_inference(url); return
    if cmd == "restore-inference":
        op_restore_inference(); return
    if cmd == "read-inference":
        op_read_inference(); return
    # 其余命令需要 state.vscdb
    if not DB_PATH.exists():
        print(f"ERROR: state.vscdb not found: {DB_PATH}")
        sys.exit(2)
    if cmd == "read":
        op_read()
    elif cmd == "status":
        op_status()
        print()
        op_read_inference()
        print()
        op_read_globalstate()
        print()
        op_read_all_globalstate()
    elif cmd == "anchor":
        url = args[1] if len(args) > 1 else DEFAULT_ANCHOR
        op_anchor(url)
    elif cmd == "restore":
        op_restore()
    elif cmd == "read-globalstate":
        op_read_globalstate()
    elif cmd == "anchor-globalstate":
        mgmt = args[1] if len(args) > 1 else DEFAULT_ANCHOR
        infer = args[2] if len(args) > 2 else mgmt
        op_anchor_globalstate(mgmt, infer)
    elif cmd == "restore-globalstate":
        op_restore_globalstate()
    # v17.53 · 一网打尽 · 包括 030 repack 等多 publisher globalState
    elif cmd == "read-all-globalstate":
        op_read_all_globalstate()
    elif cmd == "anchor-all-globalstate":
        mgmt = args[1] if len(args) > 1 else DEFAULT_ANCHOR
        infer = args[2] if len(args) > 2 else mgmt
        op_anchor_all_globalstate(mgmt, infer)
    elif cmd == "restore-all-globalstate":
        op_restore_all_globalstate()
    elif cmd in ("help", "-h", "--help"):
        print(__doc__)
    else:
        print(f"unknown cmd: {cmd}")
        print("usage: python 锚.py [--db P] [--local-state P] [--settings P]")
        print("       [read|status|anchor [url]|restore|")
        print("        read-inference|anchor-inference [url]|restore-inference|")
        print("        read-globalstate|anchor-globalstate [mgmt] [infer]|restore-globalstate|")
        print("        read-all-globalstate|anchor-all-globalstate [mgmt] [infer]|restore-all-globalstate|help]")
        sys.exit(1)


if __name__ == "__main__":
    main()
