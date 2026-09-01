"""Persisted market structure APIs. No mock-data fallback."""
from __future__ import annotations
import csv,io,json,os,re,sqlite3
from datetime import date,datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import urllib.request, urllib.error
from fastapi import APIRouter,HTTPException,Query
router=APIRouter(prefix="/api/market-structure",tags=["market-structure"])
def _db():
 p=Path(os.environ.get("VR_DATA_DIR",Path(__file__).with_name("data")));p.mkdir(parents=True,exist_ok=True);d=sqlite3.connect(p/"market_structure.sqlite3");d.row_factory=sqlite3.Row
 d.executescript("CREATE TABLE IF NOT EXISTS cffex_positions(trade_date TEXT,product TEXT,contract TEXT,member_name TEXT,rank_type TEXT,rank INTEGER,position REAL,change REAL,source_url TEXT,fetched_at TEXT,PRIMARY KEY(trade_date,product,contract,member_name,rank_type));CREATE TABLE IF NOT EXISTS etf_shares(trade_date TEXT,code TEXT,name TEXT,category TEXT,shares REAL,nav REAL,close REAL,estimated_assets REAL,share_change REAL,estimated_net_flow REAL,source TEXT,fetched_at TEXT,PRIMARY KEY(trade_date,code));");return d
def _num(v):
 try:return float(str(v).replace(',','').replace('，','').replace('%','')) if v not in (None,'') else None
 except ValueError:return None
def _txt(r,*ks):
 for k in ks:
  if r.get(k) not in (None,''):return str(r[k]).strip()
 return ''
def _get(u):
 try:
  req=urllib.request.Request(u,headers={'User-Agent':'Vibe-Research/1.0'})
  with urllib.request.urlopen(req,timeout=20) as r: raw=r.read(); ct=r.headers.get('content-type','')
 except (urllib.error.URLError, TimeoutError) as e: raise RuntimeError(f'真实数据源请求失败: {e}') from e
 if not raw: raise RuntimeError('真实数据源返回空内容')
 return raw.decode('utf-8-sig'),ct
def _rows(t,ct):
 s=t.lstrip('\ufeff \r\n\t')
 if 'json' in ct.lower() or s.startswith(('[','{')):
  x=json.loads(s)
  if isinstance(x,dict):
   x=next((x[k] for k in ('data','rows','result','items') if isinstance(x.get(k),list)),x)
  if not isinstance(x,list):raise ValueError('JSON 数据不是行列表')
  return [z for z in x if isinstance(z,dict)]
 if s.startswith('<'):
  out=[]
  for e in ET.fromstring(s).iter():
   c=list(e)
   if c and all(not list(z) for z in c):out.append({re.sub(r'[^A-Za-z0-9_\u4e00-\u9fff]','',z.tag):(z.text or '').strip() for z in c})
  if out:return out
  raise ValueError('XML 未找到数据行')
 try:dialect=csv.Sniffer().sniff(s[:2048])
 except csv.Error:dialect=csv.excel
 return [dict(x) for x in csv.DictReader(io.StringIO(s),dialect=dialect)]
def _url(t,d):return t.replace('{date}',d.replace('-','')).replace('{trade_date}',d)
def _day(d):return d or date.today().isoformat()
def _cffex(rs,d,u):
 out=[];now=datetime.utcnow().isoformat(timespec='seconds')+'Z'
 for r in rs:
  m=_txt(r,'member_name','memberName','会员简称','会员名称','member','会员')
  if not m:continue
  p=_txt(r,'product','品种','品种名称') or 'ALL';c=_txt(r,'contract','合约','合约名称') or 'ALL';rank=_num(r.get('rank') or r.get('名次'))
  lp=_num(r.get('long') or r.get('long_position') or r.get('多单持仓') or r.get('多头持仓'));sp=_num(r.get('short') or r.get('short_position') or r.get('空单持仓') or r.get('空头持仓'))
  lc=_num(r.get('long_change') or r.get('多单变化') or r.get('多头增减'));sc=_num(r.get('short_change') or r.get('空单变化') or r.get('空头增减'))
  for typ,pos,ch in (('long',lp,lc),('short',sp,sc)):
   if pos is not None:out.append((d,p,c,m,typ,int(rank) if rank is not None else None,pos,ch,u,now))
 if not out:raise ValueError('官方数据未解析出会员多空持仓行')
 return out
def sync_cffex(d):
 u=_url(os.environ.get('CFFEX_URL_TEMPLATE','https://www.cffex.com.cn/sj/ccpm/{date}/index.xml'),d);t,ct=_get(u);rows=_cffex(_rows(t,ct),d,u)
 with _db() as x:x.executemany('INSERT OR REPLACE INTO cffex_positions VALUES (?,?,?,?,?,?,?,?,?,?)',rows)
 return {'trade_date':d,'rows':len(rows),'source':u,'stored':True}
def _summary(rs):
 m={}
 for r in rs:
  x=m.setdefault(r['member_name'],{'long':0,'short':0,'long_change':0,'short_change':0});x[r['rank_type']]+=r['position'] or 0;x[r['rank_type']+'_change']+=r['change'] or 0
 for x in m.values():x['net_position']=x['long']-x['short'];x['signal']='多头增强' if x['long_change']>x['short_change'] else '空头增强' if x['short_change']>x['long_change'] else '套利/对冲或中性'
 return m
@router.post('/cffex/sync')
def cffex_sync(trade_date:str|None=Query(None)):
 try:return {'data':sync_cffex(_day(trade_date))}
 except (RuntimeError,ValueError) as e:raise HTTPException(502,str(e)) from e
@router.get('/cffex/summary')
def cffex_summary(trade_date:str|None=Query(None)):
 d=_day(trade_date)
 with _db() as x:r=x.execute('SELECT * FROM cffex_positions WHERE trade_date=?',(d,)).fetchall()
 return {'data':{'trade_date':d,'members':_summary(r),'rows':len(r),'available':bool(r),'methodology':'多空持仓分别汇总；双增/双减或净敞口较小时仅作套利/对冲候选，不能识别账户真实意图。'}}
@router.get('/cffex/history')
def cffex_history(start:str|None=Query(None),end:str|None=Query(None),member:str|None=Query(None)):
 q='SELECT * FROM cffex_positions WHERE trade_date BETWEEN ? AND ?';a=[start or '1900-01-01',end or '9999-12-31']
 if member:q+=' AND member_name LIKE ?';a.append('%'+member+'%')
 q+=' ORDER BY trade_date,member_name,product,rank_type'
 with _db() as x:o=[dict(r) for r in x.execute(q,a).fetchall()]
 return {'data':o}
def _etf(rs,d,u):
 out=[];now=datetime.utcnow().isoformat(timespec='seconds')+'Z'
 for r in rs:
  c=_txt(r,'code','代码','基金代码','symbol');s=_num(r.get('shares') or r.get('份额') or r.get('基金份额'))
  if not c or s is None:continue
  out.append((d,c,_txt(r,'name','名称','基金名称'),_txt(r,'category','分类','类别'),s,_num(r.get('nav') or r.get('单位净值') or r.get('净值')),_num(r.get('close') or r.get('收盘价') or r.get('价格')),_num(r.get('estimated_assets') or r.get('规模') or r.get('基金规模')),_num(r.get('share_change') or r.get('份额变化')),_num(r.get('estimated_net_flow') or r.get('估算净流入')),u,now))
 if not out:raise ValueError('ETF 公开数据未解析出份额行')
 return out
def sync_etf(d):
 t=os.environ.get('ETF_SHARE_SOURCE_URL','').strip()
 if not t:raise RuntimeError('未配置 ETF_SHARE_SOURCE_URL；不会使用模拟 ETF 份额数据')
 u=_url(t,d);z,ct=_get(u);rows=_etf(_rows(z,ct),d,u)
 with _db() as x:x.executemany('INSERT OR REPLACE INTO etf_shares VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',rows)
 return {'trade_date':d,'rows':len(rows),'source':u,'stored':True}
@router.post('/etf/sync')
def etf_sync(trade_date:str|None=Query(None)):
 try:return {'data':sync_etf(_day(trade_date))}
 except (RuntimeError,ValueError) as e:raise HTTPException(502,str(e)) from e
@router.get('/etf/history')
def etf_history(start:str|None=Query(None),end:str|None=Query(None),category:str|None=Query(None)):
 q='SELECT * FROM etf_shares WHERE trade_date BETWEEN ? AND ?';a=[start or '1900-01-01',end or '9999-12-31']
 if category:q+=' AND category=?';a.append(category)
 q+=' ORDER BY trade_date,code'
 with _db() as x:o=[dict(r) for r in x.execute(q,a).fetchall()]
 return {'data':o,'methodology':'份额变化不等同净申购；估算资金流需乘以单位净值/收盘价，缺失时不估算。'}
def _groups(d):
 with _db() as x:rs=x.execute('SELECT * FROM etf_shares WHERE trade_date=?',(d,)).fetchall()
 o={}
 for r in rs:
  c=r['category'] or '其他';g=next((z for z in ('中证','上证','双创','沪深50','沪深300','中证500','中证1000','金融') if z in c),'其他');a=o.setdefault(g,{'shares':0,'share_change':0,'estimated_net_flow':0,'funds':0});a['shares']+=r['shares'] or 0;a['share_change']+=r['share_change'] or 0;a['estimated_net_flow']+=r['estimated_net_flow'] or 0;a['funds']+=1
 return o
@router.get('/national-team/summary')
def national_team_summary(trade_date:str|None=Query(None)):
 d=_day(trade_date);return {'data':{'trade_date':d,'groups':_groups(d),'proxy':True,'disclaimer':'这是公开 ETF 份额变化的代理推断，不能证明国家队真实账户交易或主体身份。'}}
@router.get('/national-team/history')
def national_team_history(start:str|None=Query(None),end:str|None=Query(None)):
 with _db() as x:ds=[r[0] for r in x.execute('SELECT DISTINCT trade_date FROM etf_shares WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date',(start or '1900-01-01',end or '9999-12-31')).fetchall()]
 return {'data':[{'trade_date':d,'groups':_groups(d),'proxy':True} for d in ds],'disclaimer':'公开 ETF 份额变化代理，不等同国家队真实交易。'}