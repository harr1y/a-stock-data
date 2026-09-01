"""Persisted market-structure APIs backed only by public, real sources.

CFFEX ranking files are fetched on demand and retained with source URL, fetch
UTC timestamp and SHA-256. Missing/unreachable sources are reported as no data;
no synthetic observations are generated.
"""
from __future__ import annotations
import csv, hashlib, io, json, os, re, sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import urllib.error, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/market-structure", tags=["market-structure"])
PRODUCTS = ("IF", "IH", "IC", "IM")
POINT_VALUE = {"IF": 300, "IH": 300, "IC": 200, "IM": 200}
INDEX_SYMBOL = "000001"


def _db():
    root = Path(os.environ.get("VR_DATA_DIR", Path(__file__).with_name("data")))
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "market_structure.sqlite3")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS cffex_positions(
      trade_date TEXT, product TEXT, contract TEXT, member_name TEXT,
      rank_type TEXT, rank INTEGER, position REAL, change REAL,
      source_url TEXT, fetched_at TEXT, source_hash TEXT DEFAULT '',
      PRIMARY KEY(trade_date,product,contract,member_name,rank_type));
    CREATE TABLE IF NOT EXISTS cffex_sources(
      trade_date TEXT, product TEXT, source_url TEXT, fetched_at TEXT,
      source_hash TEXT, content_type TEXT, row_count INTEGER, status TEXT,
      error TEXT, PRIMARY KEY(trade_date,product));
    CREATE TABLE IF NOT EXISTS index_daily(
      symbol TEXT, trade_date TEXT, close REAL, change_pct REAL,
      source_url TEXT, fetched_at TEXT, source_hash TEXT,
      PRIMARY KEY(symbol,trade_date));
    CREATE TABLE IF NOT EXISTS etf_shares(
      trade_date TEXT,code TEXT,name TEXT,category TEXT,shares REAL,nav REAL,
      close REAL,estimated_assets REAL,share_change REAL,estimated_net_flow REAL,
      source TEXT,fetched_at TEXT,source_hash TEXT DEFAULT '',status TEXT DEFAULT 'ok',error TEXT DEFAULT '',PRIMARY KEY(trade_date,code));
    CREATE TABLE IF NOT EXISTS etf_category_history(
      trade_date TEXT,category TEXT,value REAL,source TEXT,fetched_at TEXT,source_hash TEXT,status TEXT,error TEXT DEFAULT '',
      PRIMARY KEY(trade_date,category));
    """)
    # Existing databases predate source audit columns.
    cols = {r[1] for r in db.execute("PRAGMA table_info(cffex_positions)")}
    if "source_hash" not in cols:
        db.execute("ALTER TABLE cffex_positions ADD COLUMN source_hash TEXT DEFAULT ''")
    etf_cols = {r[1] for r in db.execute("PRAGMA table_info(etf_shares)")}
    for name, definition in (("source_hash", "TEXT DEFAULT ''"), ("status", "TEXT DEFAULT 'ok'"), ("error", "TEXT DEFAULT ''")):
        if name not in etf_cols:
            db.execute(f"ALTER TABLE etf_shares ADD COLUMN {name} {definition}")
    return db


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("，", "").replace("%", "")) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _txt(r, *keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return str(r[k]).strip()
    return ""


def _code(value):
    text=str(value or "").strip()
    return re.sub(r"\.0$", "", text)


def _get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Vibe-Research/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            content_type = resp.headers.get("content-type", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"真实数据源请求失败: {exc}") from exc
    if not raw:
        raise RuntimeError("真实数据源返回空内容")
    # Official endpoint occasionally returns an HTML error page with HTTP 200.
    head = raw[:512].lstrip().lower()
    if b"<html" in head or b"<!doctype html" in head or b"access denied" in head:
        raise RuntimeError("官方数据源返回错误 HTML，未写入历史数据")
    return raw.decode("utf-8-sig"), content_type, raw


def _rows(text, content_type=""):
    s = text.lstrip("\ufeff \r\n\t")
    if "json" in content_type.lower() or s.startswith(("[", "{")):
        obj = json.loads(s)
        if isinstance(obj, dict):
            nested = obj.get("data")
            if isinstance(nested, dict):
                for symbol_value in nested.values():
                    if isinstance(symbol_value, dict):
                        for period_value in symbol_value.values():
                            if isinstance(period_value, list):
                                obj = period_value
                                break
                        if isinstance(obj, list):
                            break
            if isinstance(obj, dict):
                obj = next((obj[k] for k in ("data", "rows", "result", "items") if isinstance(obj.get(k), list)), obj)
        if not isinstance(obj, list):
            raise ValueError("JSON 数据不是行列表")
        return [({"trade_date": x[0], "open": x[1], "close": x[2], "high": x[3], "low": x[4], "volume": x[5]}
                 if isinstance(x, (list, tuple)) and len(x) >= 3 else x)
                for x in obj if isinstance(x, (dict, list, tuple))]
    if s.startswith("<"):
        root = ET.fromstring(s)
        out = []
        for elem in root.iter():
            children = list(elem)
            if children and all(not list(c) for c in children):
                out.append({re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]", "", c.tag): (c.text or "").strip() for c in children})
        if out:
            return out
        raise ValueError("XML 未找到数据行")
    try:
        dialect = csv.Sniffer().sniff(s[:2048])
    except csv.Error:
        dialect = csv.excel
    return [dict(x) for x in csv.DictReader(io.StringIO(s), dialect=dialect)]


def _cffex_url(product, d):
    # Official CFFEX ranking files: /sj/ccpm/YYYYMM/DD/IF.xml
    dt = datetime.strptime(d, "%Y-%m-%d")
    template = os.environ.get("CFFEX_URL_TEMPLATE", "http://www.cffex.com.cn/sj/ccpm/{yyyymm}/{dd}/{product}.xml")
    return (template.replace("{date}", d.replace("-", ""))
                   .replace("{trade_date}", d)
                   .replace("{yyyymm}", dt.strftime("%Y%m"))
                   .replace("{dd}", dt.strftime("%d"))
                   .replace("{product}", product))


def _day(value=None):
    return value or date.today().isoformat()


def _cffex_rows(records, d, product, url, digest, fetched):
    out = []
    for row in records:
        dtype = _num(row.get("datatypeid") or row.get("数据类型") or row.get("datatype"))
        if dtype == 0:
            continue
        member = _txt(row, "member_name", "shortname", "memberName", "会员简称", "会员名称", "member", "会员")
        if not member:
            continue
        contract = _txt(row, "contract", "instrumentid", "合约", "合约名称") or "ALL"
        rank = _num(row.get("rank") or row.get("名次"))
        long_pos = _num(row.get("long") or row.get("long_position") or row.get("多单持仓") or row.get("多头持仓") or row.get("持买单量"))
        short_pos = _num(row.get("short") or row.get("short_position") or row.get("空单持仓") or row.get("空头持仓") or row.get("持卖单量"))
        long_chg = _num(row.get("long_change") or row.get("多单变化") or row.get("多头增减") or row.get("持买单量增减"))
        short_chg = _num(row.get("short_change") or row.get("空单变化") or row.get("空头增减") or row.get("持卖单量增减"))
        volume = _num(row.get("volume") or row.get("持仓量"))
        change = _num(row.get("varvolume") or row.get("增减") or row.get("持仓变化"))
        if dtype == 1 and volume is not None:
            long_pos, long_chg = volume, change
        elif dtype == 2 and volume is not None:
            short_pos, short_chg = volume, change
        for typ, pos, change in (("long", long_pos, long_chg), ("short", short_pos, short_chg)):
            if pos is not None:
                out.append((d, product, contract, member, typ, int(rank) if rank is not None else None,
                            pos, change, url, fetched, digest))
    if not out:
        raise ValueError(f"{product} 官方数据未解析出会员多空持仓行")
    return out


def sync_cffex(d):
    all_rows, sources, errors = [], [], []
    for product in PRODUCTS:
        url = _cffex_url(product, d)
        fetched = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        try:
            text, content_type, raw = _get(url)
            digest = hashlib.sha256(raw).hexdigest()
            parsed = _cffex_rows(_rows(text, content_type), d, product, url, digest, fetched)
            all_rows.extend(parsed)
            sources.append((d, product, url, fetched, digest, content_type, len(parsed), "ok", ""))
        except (RuntimeError, ValueError, ET.ParseError) as exc:
            errors.append(f"{product}: {exc}")
            sources.append((d, product, url, fetched, "", "", 0, "error", str(exc)))
    with _db() as db:
        db.executemany("INSERT OR REPLACE INTO cffex_sources VALUES (?,?,?,?,?,?,?,?,?)", sources)
        if all_rows:
            db.executemany("INSERT OR REPLACE INTO cffex_positions VALUES (?,?,?,?,?,?,?,?,?,?,?)", all_rows)
    if not all_rows:
        raise RuntimeError("; ".join(errors) or "CFFEX 官方数据无有效行")
    return {"trade_date": d, "rows": len(all_rows), "products": sorted({r[1] for r in all_rows}),
            "sources": [{"product": s[1], "url": s[2], "sha256": s[4], "status": s[7], "rows": s[6]} for s in sources],
            "stored": True, "partial": bool(errors), "errors": errors}


def _member_summary(rows):
    members = {}
    for row in rows:
        item = members.setdefault(row["member_name"], {"long": 0, "short": 0, "long_change": 0, "short_change": 0, "products": {}})
        typ = row["rank_type"]
        item[typ] += row["position"] or 0
        item[typ + "_change"] += row["change"] or 0
        p = item["products"].setdefault(row["product"], {"long": 0, "short": 0, "long_change": 0, "short_change": 0, "point_value": POINT_VALUE.get(row["product"])})
        p[typ] += row["position"] or 0
        p[typ + "_change"] += row["change"] or 0
    for item in members.values():
        item["net_position"] = item["long"] - item["short"]
        if item["long_change"] > 0 and item["short_change"] <= 0:
            item["signal"] = "多头增强"
        elif item["short_change"] > 0 and item["long_change"] <= 0:
            item["signal"] = "空头增强"
        elif item["long_change"] and item["short_change"]:
            item["signal"] = "套利/对冲可能性代理"
        else:
            item["signal"] = "中性"
    return members


def _read_positions(d):
    with _db() as db:
        return db.execute("SELECT * FROM cffex_positions WHERE trade_date=?", (d,)).fetchall()


@router.post("/cffex/sync")
def cffex_sync(trade_date: str | None = Query(None)):
    try:
        return {"data": sync_cffex(_day(trade_date))}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/cffex/summary")
def cffex_summary(trade_date: str | None = Query(None)):
    d = _day(trade_date); rows = _read_positions(d)
    return {"data": {"trade_date": d, "members": _member_summary(rows), "rows": len(rows), "available": bool(rows),
                      "methodology": "会员排名是期货公司席位客户汇总，不代表期货公司自营或真实主体意图；跨品种同时保留手数与净敞口，名义金额按 IF/IH=300、IC/IM=200 元/点换算需有价格数据。"}}


@router.get("/cffex/history")
def cffex_history(start: str | None = Query(None), end: str | None = Query(None), member: str | None = Query(None), product: str | None = Query(None)):
    query = "SELECT * FROM cffex_positions WHERE trade_date BETWEEN ? AND ?"; args = [start or "1900-01-01", end or "9999-12-31"]
    if member: query += " AND member_name LIKE ?"; args.append("%" + member + "%")
    if product: query += " AND product=?"; args.append(product)
    query += " ORDER BY trade_date,member_name,product,rank_type"
    with _db() as db: data = [dict(r) for r in db.execute(query, args).fetchall()]
    return {"data": data, "available": bool(data)}


@router.get("/cffex/sources")
def cffex_sources(start: str | None = Query(None), end: str | None = Query(None)):
    with _db() as db:
        data = [dict(r) for r in db.execute("SELECT * FROM cffex_sources WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date,product", (start or "1900-01-01", end or "9999-12-31")).fetchall()]
    return {"data": data, "available": bool(data), "methodology": "每个官方文件保留 URL、抓取 UTC 时间、SHA-256、解析状态和错误信息。"}


def _weekly(rows):
    """Weekly view uses the last stored trading-day snapshot, not sums of levels."""
    buckets = {}
    for row in rows:
        day = datetime.strptime(row["trade_date"], "%Y-%m-%d").date()
        key = (day - timedelta(days=day.weekday())).isoformat()
        bucket = buckets.setdefault(key, {"week_start": key, "snapshot_date": row["trade_date"], "trading_days": set(), "long": 0, "short": 0, "long_change": 0, "short_change": 0})
        bucket["trading_days"].add(row["trade_date"])
        if row["trade_date"] > bucket["snapshot_date"]:
            bucket["snapshot_date"] = row["trade_date"]
    for bucket in buckets.values():
        snapshot = bucket["snapshot_date"]
        snap = [r for r in rows if r["trade_date"] == snapshot and (datetime.strptime(snapshot, "%Y-%m-%d").date() - timedelta(days=datetime.strptime(snapshot, "%Y-%m-%d").date().weekday())).isoformat() == bucket["week_start"]]
        for row in snap:
            typ = row["rank_type"]
            bucket[typ] += row["position"] or 0
            bucket[typ + "_change"] += row["change"] or 0
        bucket["trading_days"] = len(bucket["trading_days"])
        bucket["net_position"] = bucket["long"] - bucket["short"]
    return sorted(buckets.values(), key=lambda x: x["week_start"])


@router.get("/cffex/weekly")
def cffex_weekly(start: str | None = Query(None), end: str | None = Query(None), member: str | None = Query(None), product: str | None = Query(None)):
    data = cffex_history(start, end, member, product)["data"]
    return {"data": _weekly(data), "available": bool(data), "methodology": "周度为已留存交易日会员排名的简单汇总；缺失交易日不视为零持仓。"}


@router.post("/cffex/index/sync")
def cffex_index_sync(trade_date: str | None = Query(None)):
    d = _day(trade_date); template = os.environ.get("INDEX_HISTORY_URL_TEMPLATE", "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,2026-01-01,2027-01-01,100,qfq").strip()
    if not template:
        raise HTTPException(503, "未配置 INDEX_HISTORY_URL_TEMPLATE；无真实上证指数历史源，未写入模拟数据")
    url = template.replace("{date}", d).replace("{trade_date}", d)
    try: text, ct, raw = _get(url); obj = _rows(text, ct)
    except (RuntimeError, ValueError, ET.ParseError) as exc: raise HTTPException(502, str(exc)) from exc
    rows = []
    for r in obj:
        td = _txt(r, "trade_date", "date", "日期", "交易日期") or d
        close = _num(r.get("close") or r.get("收盘") or r.get("收盘价")); chg = _num(r.get("change_pct") or r.get("涨跌幅") or r.get("涨跌"))
        if close is not None: rows.append((INDEX_SYMBOL, td, close, chg, url, datetime.utcnow().isoformat(timespec="seconds") + "Z", hashlib.sha256(raw).hexdigest()))
    if not rows: raise HTTPException(502, "指数历史源未解析出真实收盘数据")
    with _db() as db: db.executemany("INSERT OR REPLACE INTO index_daily VALUES (?,?,?,?,?,?,?)", rows)
    return {"data": {"rows": len(rows), "source": url, "sha256": hashlib.sha256(raw).hexdigest(), "stored": True}}


def _forecast(rows, index_rows):
    # Signal is defined only from T-day changes; outcome is next stored trading day.
    by_date = {}
    for r in index_rows: by_date[r["trade_date"]] = r["close"]
    dates = sorted(by_date); result = []; correct = 0; evaluated = 0
    by_cffex = {}
    for r in rows:
        by_cffex.setdefault(r["trade_date"], {"long_change": 0, "short_change": 0})[r["rank_type"] + "_change"] += r["change"] or 0
    for i, d in enumerate(dates[:-1]):
        if d not in by_cffex: continue
        nxt = dates[i + 1]; x = by_cffex[d]; signal = "多" if x["long_change"] > x["short_change"] else "空" if x["short_change"] > x["long_change"] else "中性"
        actual = "涨" if by_date[nxt] > by_date[d] else "跌" if by_date[nxt] < by_date[d] else "平"
        hit = (signal == "多" and actual == "涨") or (signal == "空" and actual == "跌")
        if signal != "中性": evaluated += 1; correct += int(hit)
        result.append({"signal_date": d, "next_date": nxt, "signal": signal, "next_direction": actual, "correct": hit if signal != "中性" else None})
    return {"observations": result, "evaluated": evaluated, "correct": correct, "success_rate": (correct / evaluated if evaluated else None)}


@router.get("/cffex/forecast")
def cffex_forecast(start: str | None = Query(None), end: str | None = Query(None)):
    with _db() as db:
        c = db.execute("SELECT * FROM cffex_positions WHERE trade_date BETWEEN ? AND ?", (start or "1900-01-01", end or "9999-12-31")).fetchall()
        idx = db.execute("SELECT * FROM index_daily WHERE symbol=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date", (INDEX_SYMBOL, start or "1900-01-01", end or "9999-12-31")).fetchall()
    data = _forecast(c, idx)
    data.update({"available": bool(c and idx), "methodology": "严格按 T 日收盘后持仓变化预测下一条已留存交易日；不使用未来函数。成功率不代表未来收益。"})
    return {"data": data}


def _extract_etf_flow_charts(html):
    if not html or "<html" not in html.lower():
        raise ValueError("ETF_FLOW 返回内容不是 HTML")
    match = re.search(r"(?:var|const|let)\s+CHARTS\s*=\s*", html)
    if not match: raise ValueError("ETF_FLOW 页面未找到 CHARTS 数据")
    decoder=json.JSONDecoder(); payload=html[match.end():].lstrip()
    charts,_=decoder.raw_decode(payload)
    if not isinstance(charts,list) or not charts: raise ValueError("ETF_FLOW CHARTS 为空")
    out=[]
    for chart in charts:
        if not isinstance(chart,dict): continue
        category=str(chart.get("name") or chart.get("title") or chart.get("category") or "").strip()
        series=chart.get("data") or chart.get("series") or chart.get("_c1")
        if isinstance(series,dict): series=series.get("data") or series.get("values")
        if not category or not isinstance(series,list): continue
        for point in series:
            if isinstance(point,(list,tuple)) and len(point)>=2:
                td=str(point[0])[:10]; value=_num(point[1])
            elif isinstance(point,dict):
                td=_txt(point,"date","trade_date","日期"); value=_num(point.get("value") or point.get("_c1") or point.get("amount"))
            else: continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}",td) and value is not None: out.append((td,category,value))
    if not out: raise ValueError("ETF_FLOW CHARTS 未解析出日期和值")
    return out


def sync_etf_categories():
    url=os.environ.get("ETF_FLOW_URL","https://ysz-xiao.github.io/ETF_FLOW/").strip()
    text,ct,raw=_get(url); rows=_extract_etf_flow_charts(text); digest=hashlib.sha256(raw).hexdigest(); now=datetime.utcnow().isoformat(timespec="seconds")+"Z"
    with _db() as db: db.executemany("INSERT OR REPLACE INTO etf_category_history VALUES (?,?,?,?,?,?,?,?)",[(d,c,v,url,now,digest,"ok","") for d,c,v in rows])
    return {"rows":len(rows),"source":url,"sha256":digest,"stored":True}

@router.post("/etf/categories/sync")
def etf_categories_sync():
    try: return {"data":sync_etf_categories()}
    except (RuntimeError,ValueError,json.JSONDecodeError) as exc: raise HTTPException(502,str(exc)) from exc

@router.get("/etf/categories/history")
def etf_categories_history(start: str|None=Query(None), end: str|None=Query(None), category: str|None=Query(None)):
    q="SELECT * FROM etf_category_history WHERE trade_date BETWEEN ? AND ?"; a=[start or "1900-01-01",end or "9999-12-31"]
    if category: q+=" AND category LIKE ?"; a.append("%"+category+"%")
    q+=" ORDER BY trade_date,category"
    with _db() as db: data=[dict(r) for r in db.execute(q,a).fetchall()]
    return {"data":data,"available":bool(data),"methodology":"ETF_FLOW 页面公开类别序列；仅作份额/规模趋势参考，不等同资金流。"}

# ETF and public-share proxy routes retained below.
def _etf(rs, d, u):
    out=[]; now=datetime.utcnow().isoformat(timespec="seconds")+"Z"
    for r in rs:
        c=_code(_txt(r,"code","代码","基金代码","symbol")); s=_num(r.get("shares") or r.get("份额") or r.get("基金份额"))
        if not c or s is None: continue
        nav = _num(r.get("nav") or r.get("单位净值") or r.get("净值"))
        close = _num(r.get("close") or r.get("收盘价") or r.get("价格"))
        explicit_change = _num(r.get("share_change") or r.get("份额变化"))
        if explicit_change is None:
            with _db() as db:
                prev = db.execute("SELECT shares FROM etf_shares WHERE code=? AND trade_date < ? ORDER BY trade_date DESC LIMIT 1", (c, d)).fetchone()
            explicit_change = (s - prev[0]) if prev else None
        flow = _num(r.get("estimated_net_flow") or r.get("估算净流入"))
        if flow is None and explicit_change is not None and (nav is not None or close is not None):
            flow = explicit_change * (nav if nav is not None else close)
        out.append((d,c,_txt(r,"name","名称","基金名称"),_txt(r,"category","分类","类别"),s,nav,close,_num(r.get("estimated_assets") or r.get("规模") or r.get("基金规模")),explicit_change,flow,u,now))
    if not out: raise ValueError("ETF 公开数据未解析出份额行")
    return out

def _official_etf_rows(d):
    # Shanghai exchange JSON, shares are reported in ten-thousand units.
    sse_params={"isPagination":"true","pageHelp.pageSize":"10000","pageHelp.pageNo":"1","pageHelp.beginPage":"1","pageHelp.cacheSize":"1","pageHelp.endPage":"1","sqlId":"COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L","STAT_DATE":d}
    sse_url="https://query.sse.com.cn/commonQuery.do?"+urllib.parse.urlencode(sse_params)
    req=urllib.request.Request(sse_url,headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.sse.com.cn/"})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp: sse_raw=resp.read()
    except Exception as exc: raise RuntimeError(f"上交所 ETF 份额请求失败: {exc}") from exc
    if not sse_raw: raise RuntimeError("上交所 ETF 份额返回空内容")
    try: obj=json.loads(sse_raw.decode("utf-8-sig")); records=obj.get("pageHelp",{}).get("data",[])
    except Exception as exc: raise RuntimeError(f"上交所 ETF 份额 JSON 解析失败: {exc}") from exc
    rows=[]
    for r in records:
        code=_code(_txt(r,"SEC_CODE")); shares=_num(r.get("TOT_VOL"))
        if code and shares is not None: rows.append({"code":code,"name":_txt(r,"SEC_NAME"),"category":"上交所 ETF","shares":shares*10000})
    # Shenzhen exchange XLSX is an official fallback/source, not synthetic data.
    sz_params={"SHOWTYPE":"xlsx","CATALOGID":"scsj_fund_jjgm","TABKEY":"tab1","txtStart":d,"txtEnd":d,"jjlb":"ETF"}
    sz_url="https://www.szse.cn/api/report/ShowReport?"+urllib.parse.urlencode(sz_params)
    sz_req=urllib.request.Request(sz_url,headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.szse.cn/market/fund/volume/etf/index.html"})
    try:
        with urllib.request.urlopen(sz_req,timeout=20) as resp: sz_raw=resp.read()
    except Exception as exc: raise RuntimeError(f"深交所 ETF 份额请求失败: {exc}") from exc
    if sz_raw[:2] != b"PK": raise RuntimeError("深交所 ETF 份额返回非 XLSX 内容")
    try:
        import pandas as pd
        frame=pd.read_excel(io.BytesIO(sz_raw))
    except ImportError as exc: raise RuntimeError("缺少 pandas/openpyxl，无法解析深交所 ETF XLSX") from exc
    except Exception as exc: raise RuntimeError(f"深交所 ETF XLSX 解析失败: {exc}") from exc
    for _, r in frame.iterrows():
        code=_code(_txt(r.to_dict(),"基金代码")); shares=_num(r.get("基金规模(份)"))
        if code and shares is not None: rows.append({"code":code,"name":_txt(r.to_dict(),"基金简称"),"category":"深交所 ETF","shares":shares})
    if not rows: raise RuntimeError("交易所 ETF 份额均未解析出有效行")
    # Return one combined raw digest to make the audit reproducible.
    return rows, sse_url+" | "+sz_url, sse_raw+b"\n"+sz_raw


def sync_etf(d):
    template=os.environ.get("ETF_SHARE_SOURCE_URL","").strip()
    if template:
        u=template.replace("{date}",d).replace("{trade_date}",d); z,ct,raw=_get(u); rows=_etf(_rows(z,ct),d,u)
    else:
        records,u,raw=_official_etf_rows(d); rows=_etf(records,d,u)
    digest=hashlib.sha256(raw).hexdigest(); rows=[r+(digest,"ok","") for r in rows]
    with _db() as db: db.executemany("INSERT OR REPLACE INTO etf_shares VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",rows)
    return {"trade_date":d,"rows":len(rows),"source":u,"sha256":digest,"stored":True}

@router.post("/etf/sync")
def etf_sync(trade_date: str | None = Query(None)):
    try: return {"data": sync_etf(_day(trade_date))}
    except (RuntimeError,ValueError) as exc: raise HTTPException(502,str(exc)) from exc

@router.get("/etf/history")
def etf_history(start: str | None = Query(None), end: str | None = Query(None), category: str | None = Query(None)):
    q="SELECT * FROM etf_shares WHERE trade_date BETWEEN ? AND ?"; a=[start or "1900-01-01",end or "9999-12-31"]
    if category: q+=" AND category=?"; a.append(category)
    q+=" ORDER BY trade_date,code"
    with _db() as db: data=[dict(r) for r in db.execute(q,a).fetchall()]
    return {"data":data,"available":bool(data),"methodology":"份额变化不等同净申购；估算资金流需乘以单位净值/收盘价，缺失时不估算。"}

def _groups(d):
    with _db() as db: rs=db.execute("SELECT * FROM etf_shares WHERE trade_date=?",(d,)).fetchall()
    out={}
    # Match the most specific broad-index labels first; "中证" must not swallow CSI 500/1000.
    labels=("上证50","沪深300","中证500","中证1000","科创50","双创","金融","中证","上证")
    for r in rs:
        text=" ".join(str(r[k] or "") for k in ("name","category"))
        g=next((z for z in labels if z in text),"其他")
        x=out.setdefault(g,{"shares":0,"share_change":0,"estimated_net_flow":0,"funds":0,"buy_shares":0,"sell_shares":0})
        change=r["share_change"]
        x["shares"]+=r["shares"] or 0; x["share_change"]+=change or 0; x["estimated_net_flow"]+=r["estimated_net_flow"] or 0; x["funds"]+=1
        if change is not None:
            if change>0: x["buy_shares"]+=change
            elif change<0: x["sell_shares"]+=abs(change)
    for x in out.values():
        total=x["buy_shares"]+x["sell_shares"]
        x["buy_ratio"]=(x["buy_shares"]/total) if total else None
        x["sell_ratio"]=(x["sell_shares"]/total) if total else None
    return out

@router.get("/national-team/summary")
def national_team_summary(trade_date: str | None = Query(None)):
    d=_day(trade_date); return {"data":{"trade_date":d,"groups":_groups(d),"proxy":True,"disclaimer":"这是公开 ETF 份额变化的代理推断，不能证明国家队真实账户交易或主体身份。"}}

@router.get("/national-team/history")
def national_team_history(start: str | None = Query(None), end: str | None = Query(None)):
    with _db() as db: dates=[r[0] for r in db.execute("SELECT DISTINCT trade_date FROM etf_shares WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",(start or "1900-01-01",end or "9999-12-31")).fetchall()]
    return {"data":[{"trade_date":d,"groups":_groups(d),"proxy":True} for d in dates],"available":bool(dates),"disclaimer":"公开 ETF 份额变化代理，不等同国家队真实交易。"}
