"""
Yandex Cloud Function — приёмник результатов викторины «Точка роста».

Принимает POST с JSON:
    {"name":"Иванов Артём","cls":"6","score":22,"total":22,"secs":143,"ts":"09.10.2026 14:30"}

Дописывает строку в конец таблицы Яндекс.

Проверка: откройте адрес функции с параметром ?check=1 —
функция сама скажет, работает ли доступ к таблице.
"""

import json
import os
import urllib.request
import urllib.error
import urllib.parse

# ───────────────────────── НАСТРОЙКИ ─────────────────────────
# Идентификатор таблицы — это часть ссылки вида
#   https://docs.google.com/... НЕТ:
#   https://yandex.ru/table-XXXXXXXXXXXXXXXX/  →  XXXXXXXXXXXXXXXX
TABLE_ID = os.environ.get("TABLE_ID", "")
# Имя листа (как он называется во вкладке внизу)
SHEET = os.environ.get("SHEET", "Лист1")

# Версии API — перебираются по очереди, сработает та, что живая.
API_VERSIONS = os.environ.get("API_VERSIONS", "v3,v2,v4").split(",")
# Лист для записи данных (обычно отдельный от «шапки»)
RANGE = os.environ.get("RANGE", "")
# Заголовок таблицы — записывается один раз, при первой отправке
HEADER = ["Дата и время", "Класс", "Участник", "Баллы", "Максимум",
          "Время (сек)", "Время прохождения"]

# В какой строке искать конец таблицы (заполняется при первом запуске)
FIRST_DATA_ROW = int(os.environ.get("FIRST_DATA_ROW", "2"))

METADATA_URLS = [
    "http://169.254.254.254/computeMetadata/v1/instance/service-accounts/default/token",
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
]
API_HOST = os.environ.get("API_HOST", "https://yandex.ru")


# ─────────────────────── ТОКЕН СЕРВИСНОГО АККАУНТА ───────────────────────
_token_cache = {"token": None, "exp": 0}


def get_token():
    """Берём IAM-токен у сервисного аккаунта функции через metadata."""
    import time
    if _token_cache["token"] and _token_cache["exp"] > time.time() + 60:
        return _token_cache["token"]

    last = None
    for url in METADATA_URLS:
        try:
            req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
            tok = data.get("access_token")
            if tok:
                _token_cache["token"] = tok
                _token_cache["exp"] = time.time() + int(data.get("expires_in", 3600))
                return tok
        except Exception as e:                      # noqa: BLE001
            last = e

    raise RuntimeError(
        "Не удалось получить IAM-токен ({0}). Функции нужен сервисный аккаунт: "
        "укажите его в настройках функции.".format(last)
    )


# ───────────────────────── ЗАПИСЬ В ТАБЛИЦУ ─────────────────────────
def sheet_call(method, path, token, payload=None):
    """Один вызов к API таблиц. Возвращает (status, text)."""
    url = "{0}/yandexcloud/api/spreadsheets/{1}/spreadsheets/{2}{3}".format(
        API_HOST, method, TABLE_ID, path)
    body = None
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                          # noqa: BLE001
        return 0, str(e)


def append_row(values, version):
    """Пишет values в лист. Пробует patch (заменить диапазон), затем post."""
    rng = RANGE or ("'{0}'!A1:G1".format(SHEET))
    hdr = {"Authorization": "Bearer " + get_token()}
    query = urllib.parse.urlencode({"range": rng})
    body = json.dumps({"values": [values]}, ensure_ascii=False).encode("utf-8")
    hdr["Content-Type"] = "application/json"

    url = "{0}/yandexcloud/api/spreadsheets/{1}/spreadsheets/{2}/values?{3}".format(
        API_HOST, version, TABLE_ID, query)

    for m in ("patch", "post"):
        req = urllib.request.Request(url, data=body, headers=hdr, method=m.upper())
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if 200 <= r.status < 300:
                    return True, "{0} {1} → OK ({2})".format(m.upper(), rng, r.status)
        except urllib.error.HTTPError as e:
            last = "{0} {1} → HTTP {2}: {3}".format(
                m.upper(), rng, e.code, e.read().decode("utf-8", "replace")[:200])
        except Exception as e:                      # noqa: BLE001
            last = "{0} → {1}".format(m.upper(), e)
    return False, last


def find_free_row(version):
    """Ищет первую свободную строку ниже шапки."""
    rng = "'{0}'!A{1}:G{2}".format(SHEET, FIRST_DATA_ROW, FIRST_DATA_ROW + 300)
    url = ("{0}/yandexcloud/api/spreadsheets/{1}/spreadsheets/{2}/values?{3}").format(
        API_HOST, version, TABLE_ID,
        urllib.parse.urlencode({"range": rng, "includeGridData": "false"}))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + get_token()})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:                                # noqa: BLE001
        return FIRST_DATA_ROW

    rows = data.get("values") or data.get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", [])
    offset = FIRST_DATA_ROW
    for i, row in enumerate(rows):
        vals = row if isinstance(row, list) else []
        if not any(str(v).strip() for v in vals):
            return offset + i
    return offset + max(len(rows), 1)


def check():
    """Диагностика: токен есть? таблица видна?"""
    out = {"table_id": TABLE_ID or "НЕ ЗАДАН", "sheet": SHEET}
    try:
        get_token()
        out["token"] = "получен ✅"
    except Exception as e:                          # noqa: BLE001
        out["token"] = "ОШИБКА: {0}".format(e)
        return out

    out["attempts"] = []
    for v in API_VERSIONS:
        st, txt = sheet_call("get", "", get_token())
        out["attempts"].append({
            "version": v,
            "GET /spreadsheets/{id}": st,
            "ответ": txt[:180],
        })
    return out


# ─────────────────────────── ОБРАБОТЧИК ───────────────────────────
def mmss(s):
    s = int(s or 0)
    return "{0} мин {1:02d} сек".format(s // 60, s % 60)


def handler(event, context):
    body = (event.get("body") or "").strip()

    # GET /?check=1 — самопроверка
    if not body:
        qs = (event.get("queryString") or "")
        if "check" in qs:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json; charset=utf-8",
                            "Access-Control-Allow-Origin": "*"},
                "body": json.dumps(check(), ensure_ascii=False, indent=2),
            }
        return {"statusCode": 200, "headers": {"Access-Control-Allow-Origin": "*"},
                "body": "Приёмник результатов работает."}

    # OPTIONS — preflight
    if (event.get("headers") or {}).get("origin") and not body:
        return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"},
                "body": ""}

    try:
        d = json.loads(body)
    except Exception:                                # noqa: BLE001
        return {"statusCode": 400, "headers": {"Access-Control-Allow-Origin": "*"},
                "body": "не JSON"}

    name = str(d.get("name", ""))[:80]
    cls = str(d.get("cls", ""))[:10]
    score = d.get("score")
    total = d.get("total", 22)
    secs = d.get("secs", 0)

    if not TABLE_ID:
        return {"statusCode": 500, "headers": {"Access-Control-Allow-Origin": "*"},
                "body": "TABLE_ID не задан"}

    row = [str(d.get("ts", "")), cls, name, score, total, secs, mmss(secs)]
    errors = []
    for v in API_VERSIONS:
        try:
            n = find_free_row(v)
            ok, info = append_row_at(row, n, v)
            if ok:
                return {"statusCode": 200,
                        "headers": {"Content-Type": "application/json",
                                    "Access-Control-Allow-Origin": "*"},
                        "body": json.dumps({"ok": True, "row": n, "version": v},
                                           ensure_ascii=False)}
            errors.append(info)
        except Exception as e:                      # noqa: BLE001
            errors.append("{0}: {1}".format(v, e))

    return {"statusCode": 502, "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"ok": False, "errors": errors}, ensure_ascii=False)}


def append_row_at(values, row_num, version):
    """Пишет значения в конкретную строку листа."""
    rng = "'{0}'!A{1}:G{1}".format(SHEET, row_num)
    url = "{0}/yandexcloud/api/spreadsheets/{1}/spreadsheets/{2}/values?{3}".format(
        API_HOST, version, TABLE_ID, urllib.parse.urlencode({"range": rng}))
    body = json.dumps({"values": [values]}, ensure_ascii=False).encode("utf-8")
    hdr = {"Authorization": "Bearer " + get_token(),
           "Content-Type": "application/json"}

    last = ""
    for m in ("patch", "post"):
        req = urllib.request.Request(url, data=body, headers=hdr, method=m.upper())
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if 200 <= r.status < 300:
                    return True, "строка {0} {1}".format(row_num, rng)
        except urllib.error.HTTPError as e:
            last = "{0} HTTP {1}: {2}".format(
                m.upper(), e.code, e.read().decode("utf-8", "replace")[:250])
        except Exception as e:                      # noqa: BLE001
            last = "{0}: {1}".format(m.upper(), e)
    return False, last