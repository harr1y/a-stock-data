import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Database, RefreshCw, ShieldAlert,
} from "lucide-react";
import { EChart } from "@/components/ui/EChart";
import {
  ApiError, api, CffexSummary, CffexForecast, CffexPositionRow, EtfShareRow, NationalTeamSummary, NationalTeamHistoryRow,
} from "@/lib/api";

type Tab = "cffex" | "etf-flow" | "national-team";
const tabs: Array<{ key: Tab; label: string; desc: string }> = [
  { key: "cffex", label: "中金所多空", desc: "股指期货会员多空持仓与次日验证" },
  { key: "etf-flow", label: "ETF 份额", desc: "公开份额变化与估算资金流" },
  { key: "national-team", label: "宽基代理", desc: "公开 ETF 份额变化的国家队代理推断" },
];

function dateToIso(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const isoDate = () => dateToIso(new Date());

function fmt(n: number | null | undefined, digits = 2) {
  return n == null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function Empty({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}




function CffexPanel({ date }: { date: string }) {
  const [data, setData] = useState<CffexSummary | null>(null);
  const [history, setHistory] = useState<CffexPositionRow[]>([]);
  const [weeklySummary, setWeeklySummary] = useState<Array<{ week_start: string; snapshot_date: string; trading_days: number; aggregate: any; citic: any; strategy: any; daily: any[] }>>([]);
  const [forecast, setForecast] = useState<CffexForecast | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = async (refresh = false) => { setBusy(true); setError(""); try {
    if (refresh) await api.cffexSync(date);
    const start = `${Math.max(2000, Number(date.slice(0, 4)) - 1)}-01-01`;
    const [summary, rows, weeks, pred] = await Promise.all([api.cffexSummary(date), api.cffexHistory(start, date), api.cffexWeeklySummary(start, date), api.cffexForecast(start, date)]);
    setData(summary); setHistory(rows); setWeeklySummary(weeks); setForecast(pred);
  } catch (e) { setError(e instanceof ApiError ? e.message : "中金所数据加载失败"); } finally { setBusy(false); } };
  useEffect(() => { void load(false); }, [date]);
  const rows = useMemo(() => Object.entries(data?.members || {}).sort((a, b) => b[1].net_position - a[1].net_position), [data]);
  const daily = useMemo(() => { const m = new Map<string, { long: number; short: number; net: number }>(); history.forEach(r => { const x=m.get(r.trade_date)||{long:0,short:0,net:0}; if(r.rank_type === "long") x.long += r.position || 0; if(r.rank_type === "short") x.short += r.position || 0; x.net=x.long-x.short; m.set(r.trade_date,x); }); return [...m.entries()].sort((a,b)=>a[0].localeCompare(b[0])); }, [history]);
  const line = { tooltip:{trigger:"axis"}, legend:{data:["多单","空单","净敞口"]}, xAxis:{type:"category",data:daily.map(([d])=>d)}, yAxis:{type:"value",name:"手"}, series:[{name:"多单",type:"line",data:daily.map(([,v])=>v.long)},{name:"空单",type:"line",data:daily.map(([,v])=>v.short)},{name:"净敞口",type:"line",data:daily.map(([,v])=>v.net)}] };
  const all = data?.aggregate; const citic = data?.citic; const card = (label:string, x:any) => <div className="rounded-xl border border-border bg-card p-4"><div className="text-sm font-medium">{label}</div><div className="mt-3 grid grid-cols-2 gap-2 text-sm"><span>总多单 <b>{fmt(x?.long_hands,0)}</b> 手</span><span>总空单 <b>{fmt(x?.short_hands,0)}</b> 手</span><span>多单变化 <b>{fmt(x?.long_change_hands,0)}</b></span><span>空单变化 <b>{fmt(x?.short_change_hands,0)}</b></span></div><div className="mt-3 text-xs text-muted-foreground">净持仓 {fmt(x?.net_position,0)} 手 · 净变化 {fmt(x?.net_change,0)} 手</div></div>;
  return <><div className="mb-4 flex items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">中金所股指期货多空总结</h2><p className="text-xs text-muted-foreground">{date} 官方披露可见会员/合约行汇总；中信期货为会员名称含“中信期货”的公开行；常规持仓方向与 A 股 T+1 反向经验分别展示。</p></div><button onClick={()=>void load(true)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><RefreshCw className={busy?"h-4 w-4 animate-spin":"h-4 w-4"}/>拉取当日</button></div>{error&&<div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!data?.available?<Empty message="暂无已保存的中金所数据。点击‘拉取当日’请求官方源。"/>:<div className="space-y-4"><div className="grid gap-3 md:grid-cols-2">{card("全部会员总计",all)}{card("中信相关会员总计",citic)}</div><div className="rounded-xl border border-primary/30 bg-primary/5 p-4"><div className="flex flex-wrap items-center gap-3"><span className="text-sm font-medium">今日策略判断：{data.strategy?.label || "观望"}</span><span className="rounded-full border border-border px-2 py-1 text-xs">{data.strategy?.action || "结合指数确认"}</span><span className="rounded-full border border-border px-2 py-1 text-xs">T+1：{data.strategy?.forecast_label || "待定"}</span></div><p className="mt-2 text-sm text-muted-foreground">{data.strategy?.rationale || "暂无足够的多空变化数据。"} {data.strategy?.citic_note || ""}</p></div><div className="rounded-xl border border-border bg-card p-3"><EChart option={line} height={320}/></div><div className="rounded-xl border border-border p-4"><h3 className="mb-3 text-sm font-medium">上一周及历史周汇总（每周最后一个已留存交易日）</h3>{weeklySummary.length?<div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-muted-foreground"><tr><th className="p-2">周起始</th><th className="p-2">快照日</th><th className="p-2">全部多/空</th><th className="p-2">中信期货多/空</th><th className="p-2">常规判断 / T+1</th></tr></thead><tbody>{weeklySummary.slice(-12).map(w=><tr className="border-t border-border/60" key={w.week_start}><td className="p-2">{w.week_start}</td><td className="p-2">{w.snapshot_date}</td><td className="p-2">{fmt(w.aggregate?.long_hands,0)} / {fmt(w.aggregate?.short_hands,0)}</td><td className="p-2">{fmt(w.citic?.long_hands,0)} / {fmt(w.citic?.short_hands,0)}</td><td className="p-2">{w.strategy?.label || "观望"} / {w.strategy?.forecast_label || "待定"}</td></tr>)}</tbody></table></div>:<p className="text-sm text-muted-foreground">暂无已留存周数据。</p>}</div><div className="rounded-xl border border-border p-4"><h3 className="text-sm font-medium">T+1 上证方向验证</h3><p className="mt-2 text-sm text-muted-foreground">{forecast?.evaluated?`样本 ${forecast.evaluated}，命中 ${forecast.correct}，成功率 ${fmt((forecast.success_rate||0)*100)}%`:`暂无可评估样本，不显示虚构胜率。`}</p></div><div className="overflow-x-auto rounded-xl border border-border"><table className="w-full text-sm"><thead className="bg-muted/30 text-left text-muted-foreground"><tr><th className="p-3">会员</th><th className="p-3">多单</th><th className="p-3">空单</th><th className="p-3">净敞口</th><th className="p-3">判断</th></tr></thead><tbody>{rows.slice(0,30).map(([name,v])=><tr className="border-t border-border/60" key={name}><td className="p-3 font-medium">{name}</td><td className="p-3">{fmt(v.long,0)} / {fmt(v.long_change,0)}</td><td className="p-3">{fmt(v.short,0)} / {fmt(v.short_change,0)}</td><td className="p-3">{fmt(v.net_position,0)}</td><td className="p-3">{v.signal}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground">口径限制：会员排名是期货公司席位客户汇总，不等于期货公司自营；“套利/对冲”只是公开多空同时变化的代理判断，不代表真实机构意图。周度缺失交易日不补零。</p></div>}</>;
}

function EtfPanel({ date }: { date: string }) {
  const [range, setRange] = useState(1);
  const [rows, setRows] = useState<EtfShareRow[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = async (refresh = false) => { setBusy(true); setError(""); try { if (refresh) await api.etfSync(date); setRows(await api.etfHistory(new Date(new Date(date).setFullYear(new Date(date).getFullYear() - range)).toISOString().slice(0, 10), date)); } catch (e) { setError(e instanceof ApiError ? e.message : "ETF 份额加载失败"); } finally { setBusy(false); } };
  useEffect(() => { void load(false); }, [date, range]);
  const daily = useMemo(() => Object.entries(rows.reduce<Record<string, { shares: number; flow: number }>>((a, r) => { const x = a[r.trade_date] || { shares: 0, flow: 0 }; x.shares += r.share_change || 0; x.flow += r.estimated_net_flow || 0; a[r.trade_date] = x; return a; }, {})).sort((a, b) => a[0].localeCompare(b[0])), [rows]);
  const chart = { tooltip: { trigger: "axis" }, legend: { data: ["份额变化", "估算资金流"] }, xAxis: { type: "category", data: daily.map(([d]) => d) }, yAxis: [{ type: "value", name: "份额变化" }, { type: "value", name: "估算资金流" }], series: [{ name: "份额变化", type: "line", smooth: true, data: daily.map(([, v]) => v.shares) }, { name: "估算资金流", type: "line", smooth: true, yAxisIndex: 1, data: daily.map(([, v]) => v.flow) }] };
  return <><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">ETF 份额分析</h2><p className="text-xs text-muted-foreground">份额变化不等同资金流；估算资金流仅在公开净值或收盘价可用时计算。</p></div><div className="mb-3 flex gap-1">{[1, 3, 5, 10].map(y => <button key={y} onClick={() => setRange(y)} className={"rounded-md border px-2 py-1 text-xs " + (range === y ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground")}>{y}年</button>)}</div><button onClick={() => void load(true)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><RefreshCw className={busy ? "h-4 w-4 animate-spin" : "h-4 w-4"} />拉取当日</button></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!rows.length ? <Empty message="暂无已保存的 ETF 份额数据。点击‘拉取当日’请求配置的真实公开源。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={320} /></div><div className="rounded-xl border border-border p-4 text-sm">已保存 {rows.length} 条 ETF 记录、{daily.length} 个交易日；区间估算资金流：{fmt(rows.reduce((sum, r) => sum + (r.estimated_net_flow || 0), 0))}。下方趋势仅表示公开份额变化与条件估算，不等同真实资金流。</div></div>}</>;
}

function NationalPanel({ date }: { date: string }) {
  const [data, setData] = useState<NationalTeamSummary | null>(null); const [history, setHistory] = useState<NationalTeamHistoryRow[]>([]); const [error, setError] = useState("");
  useEffect(() => { const end=date; const start=new Date(new Date(end).setFullYear(new Date(end).getFullYear()-1)).toISOString().slice(0,10); Promise.all([api.nationalTeamSummary(date), api.nationalTeamHistory(start,end)]).then(([summary, rows]) => { setData(summary); setHistory(rows); }).catch(e => setError(e instanceof ApiError ? e.message : "宽基代理数据加载失败")); }, [date]);
  const groups = Object.entries(data?.groups || {});
  const names = useMemo(() => Array.from(new Set(history.flatMap(row => Object.keys(row.groups || {})))), [history]);
  const chart = { tooltip: { trigger: "axis" }, legend: { data: names }, xAxis: { type: "category", data: history.map(row => row.trade_date) }, yAxis: { type: "value", name: "估算资金流" }, series: names.map(name => ({ name, type: "line", smooth: true, data: history.map(row => row.groups?.[name]?.estimated_net_flow ?? null) })) };
  return <><div className="mb-4"><h2 className="text-lg font-semibold">宽基 ETF “国家队”代理</h2><p className="text-xs text-muted-foreground">仅依据公开 ETF 份额变化推断宽基行为，不能证明国家队真实账户交易或主体身份。</p></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!groups.length ? <Empty message="暂无该日期的宽基份额数据；请先在 ETF 份额页拉取并保存真实数据。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={300} /></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{groups.map(([name, v]) => <div className="rounded-xl border border-border p-4" key={name}><div className="text-sm font-medium">{name}</div><div className="mt-2 text-lg">{fmt(v.estimated_net_flow)}</div><div className="text-xs text-muted-foreground">份额变化 {fmt(v.share_change)} · ETF 数 {v.funds}</div><div className="mt-1 text-xs text-muted-foreground">买入比例 {v.buy_ratio == null ? "—" : `${(v.buy_ratio * 100).toFixed(1)}%`} · 卖出比例 {v.sell_ratio == null ? "—" : `${(v.sell_ratio * 100).toFixed(1)}%`}</div></div>)}</div></div>}</>;
}

export function MarketStructure() {
  const { tab = "cffex" } = useParams<{ tab: Tab }>(); const navigate = useNavigate(); const active = tabs.some(t => t.key === tab) ? tab as Tab : "cffex"; const [date, setDate] = useState(isoDate());
  return <div className="space-y-5"><div><div className="flex items-center gap-2"><Database className="h-5 w-5 text-primary" /><h1 className="text-2xl font-bold">市场结构</h1></div><p className="mt-1 text-sm text-muted-foreground">中金所多空、ETF 份额与宽基代理的可追溯研究工作台。</p></div><div className="flex flex-wrap gap-2 rounded-xl border border-border bg-card p-2">{tabs.map(t => <button key={t.key} onClick={() => navigate("/market-structure/" + t.key)} className={"rounded-lg px-3 py-2 text-left text-sm " + (active === t.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted/50")}><span className="block font-medium">{t.label}</span><span className="text-[11px] opacity-80">{t.desc}</span></button>)}<label className="ml-auto flex items-center gap-2 px-2 text-sm text-muted-foreground">日期<input type="date" value={date} onChange={e => setDate(e.target.value)} className="rounded-md border border-border bg-background px-2 py-1 text-foreground" /></label></div>{active === "cffex" && <CffexPanel date={date} />}{active === "etf-flow" && <EtfPanel date={date} />}{active === "national-team" && <NationalPanel date={date} />}<div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-muted-foreground"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />所有信号均为公开数据分析或代理推断，不构成投资建议；数据源异常时请以“无数据”为准。</div></div>;
}
