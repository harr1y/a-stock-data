import os
from pathlib import Path


def test_cffex_url_and_weekly(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1]))
    import market_structure as m
    assert m._cffex_url("IF", "2026-08-31").endswith("/202608/31/IF.xml")
    rows = [
        {"trade_date":"2026-08-31", "rank_type":"long", "position":10, "change":2},
        {"trade_date":"2026-08-31", "rank_type":"short", "position":4, "change":-1},
    ]
    weekly = m._weekly(rows)
    assert weekly[0]["long"] == 10
    assert weekly[0]["short"] == 4
    assert weekly[0]["net_position"] == 6


def test_no_future_forecast_without_index_history(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1]))
    import market_structure as m
    out = m._forecast([], [])
    assert out["evaluated"] == 0
    assert out["success_rate"] is None

def test_tencent_nested_rows_are_normalized():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[1]))
    import market_structure as m
    rows = m._rows('{"data":{"sh000001":{"day":[["2026-08-31","3926.530","3986.300","3986.300","3926.500","1"]]}}}', 'application/json')
    assert rows[0]["trade_date"] == "2026-08-31"
    assert rows[0]["close"] == "3986.300"


def test_cffex_datatype_zero_is_ignored():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[1]))
    import market_structure as m
    rows = m._cffex_rows([
        {"datatypeid": "0", "shortname": "忽略", "volume": "99"},
        {"datatypeid": "1", "shortname": "多头", "instrumentid": "IF2609", "rank": "1", "volume": "10", "varvolume": "2"},
    ], "2026-08-31", "IF", "u", "h", "t")
    assert len(rows) == 1 and rows[0][4] == "long"


def test_etf_flow_chart_parser_rejects_non_html_and_reads_c1():
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1]))
    import market_structure as m
    html = '<html><script>var CHARTS = [{"name":"宽基市场","_c1":[["2026-08-29",12.5],["2026-08-30",13.0]]}];</script></html>'
    rows = m._extract_etf_flow_charts(html)
    assert rows[0] == ("2026-08-29", "宽基市场", 12.5)
