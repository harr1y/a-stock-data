import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Database, RefreshCw, ShieldAlert,
} from "lucide-react";
import { EChart } from "@/components/ui/EChart";
import {
  ApiError, api, CffexSummary, CffexForecast, EtfShareRow, NationalTeamSummary, NationalTeamHistoryRow,
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
  const [data, setData] = useState<CffexSummary | null>(null); const [forecast, setForecast] = useState<CffexForecast | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = async (refresh = false) => { setBusy(true); setError(""); try { if (refresh) await api.cffexSync(date); const [summary, pred] = await Promise.all([api.cffexSummary(date), api.cffexForecast(date, date)]); setData(summary); setForecast(pred); } catch (e) { setError(e instanceof ApiError ? e.message : "中金所数据加载失败"); } finally { setBusy(false); } };
  useEffect(() => { void load(false); }, [date]);
  const rows = useMemo(() => Object.entries(data?.members || {}).sort((a, b) => b[1].net_position - a[1].net_position), [data]);
  const chart = useMemo(() => ({ tooltip: { trigger: "axis" }, legend: { data: ["多单", "空单"] }, xAxis: { type: "category", data: rows.slice(0, 12).map(([n]) => n) }, yAxis: { type: "value", name: "手" }, series: [{ name: "多单", type: "bar", data: rows.slice(0, 12).map(([, v]) => v.long) }, { name: "空单", type: "bar", data: rows.slice(0, 12).map(([, v]) => v.short) }] }), [rows]);
  return <><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">中金所股指期货会员多空</h2><p className="text-xs text-muted-foreground">官方披露范围内的会员结算汇总，不代表期货公司自营或真实主体意图。</p></div><button onClick={() => void load(true)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><RefreshCw className={busy ? "h-4 w-4 animate-spin" : "h-4 w-4"} />拉取当日</button></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!data?.available ? <Empty message="暂无已保存的中金所数据。点击‘拉取当日’后才会请求官方源；真实源失败时不会填充模拟值。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={320} /></div><div className="overflow-x-auto rounded-xl border border-border"><table className="w-full text-sm"><thead className="bg-muted/30 text-left text-muted-foreground"><tr><th className="p-3">会员</th><th className="p-3">多单</th><th className="p-3">空单</th><th className="p-3">净敞口</th><th className="p-3">信号</th></tr></thead><tbody>{rows.map(([name, v]) => <tr className="border-t border-border/60" key={name}><td className="p-3 font-medium">{name}</td><td className="p-3">{fmt(v.long)}</td><td className="p-3">{fmt(v.short)}</td><td className="p-3">{fmt(v.net_position)}</td><td className="p-3">{v.signal}</td></tr>)}</tbody></table></div><div className="grid gap-3 md:grid-cols-3"><div className="rounded-xl border border-border p-4"><div className="text-sm font-medium">周度汇总</div><div className="mt-2 text-sm text-muted-foreground">暂无已保存的周度聚合；需后端按交易日历史计算。</div></div><div className="rounded-xl border border-border p-4"><div className="text-sm font-medium">T+1 预测成功率</div><div className="mt-2 text-sm text-muted-foreground">{forecast?.evaluated ? `${(forecast.success_rate! * 100).toFixed(1)}%（${forecast.correct}/${forecast.evaluated}）` : "暂无可评估样本"}</div></div><div className="rounded-xl border border-border p-4"><div className="text-sm font-medium">来源审计</div><div className="mt-2 text-sm text-muted-foreground">拉取结果会记录官方源 URL 与抓取时间；当前摘要接口未返回来源明细。</div></div></div><p className="text-xs text-muted-foreground">当前接口返回 T 日持仓摘要；会员排名是期货公司席位客户汇总，不代表期货公司自营或真实主体意图。</p></div>}</>;
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
