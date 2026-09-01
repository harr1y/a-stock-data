import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { RefreshCw, Database, ShieldAlert } from "lucide-react";
import { EChart } from "@/components/ui/EChart";
import { ApiError, api, CffexSummary, EtfShareRow, NationalTeamSummary } from "@/lib/api";

type Tab = "cffex" | "etf-flow" | "national-team";
const tabs: Array<{ key: Tab; label: string; desc: string }> = [
  { key: "cffex", label: "中金所多空", desc: "股指期货会员多空持仓与次日验证" },
  { key: "etf-flow", label: "ETF 份额", desc: "公开份额变化与估算资金流" },
  { key: "national-team", label: "宽基代理", desc: "公开 ETF 份额变化的国家队代理推断" },
];
const isoDate = () => new Date().toISOString().slice(0, 10);
const fmt = (n: number | null | undefined) => n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
function Empty({ message }: { message: string }) { return <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">{message}</div>; }

function CffexPanel({ date }: { date: string }) {
  const [data, setData] = useState<CffexSummary | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = async (refresh = false) => { setBusy(true); setError(""); try { if (refresh) await api.cffexSync(date); setData(await api.cffexSummary(date)); } catch (e) { setError(e instanceof ApiError ? e.message : "中金所数据加载失败"); } finally { setBusy(false); } };
  useEffect(() => { void load(false); }, [date]);
  const rows = useMemo(() => Object.entries(data?.members || {}).sort((a, b) => b[1].net_position - a[1].net_position), [data]);
  const chart = useMemo(() => ({ tooltip: { trigger: "axis" }, legend: { data: ["多单", "空单"] }, xAxis: { type: "category", data: rows.slice(0, 12).map(([n]) => n) }, yAxis: { type: "value", name: "手" }, series: [{ name: "多单", type: "bar", data: rows.slice(0, 12).map(([, v]) => v.long) }, { name: "空单", type: "bar", data: rows.slice(0, 12).map(([, v]) => v.short) }] }), [rows]);
  return <><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">中金所股指期货会员多空</h2><p className="text-xs text-muted-foreground">官方披露范围内的会员结算汇总，不代表期货公司自营或真实主体意图。</p></div><button onClick={() => void load(true)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><RefreshCw className={busy ? "h-4 w-4 animate-spin" : "h-4 w-4"} />拉取当日</button></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!data?.available ? <Empty message="暂无已保存的中金所数据。点击‘拉取当日’后才会请求官方源；真实源失败时不会填充模拟值。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={320} /></div><div className="overflow-x-auto rounded-xl border border-border"><table className="w-full text-sm"><thead className="bg-muted/30 text-left text-muted-foreground"><tr><th className="p-3">会员</th><th className="p-3">多单</th><th className="p-3">空单</th><th className="p-3">净敞口</th><th className="p-3">信号</th></tr></thead><tbody>{rows.map(([name, v]) => <tr className="border-t border-border/60" key={name}><td className="p-3 font-medium">{name}</td><td className="p-3">{fmt(v.long)}</td><td className="p-3">{fmt(v.short)}</td><td className="p-3">{fmt(v.net_position)}</td><td className="p-3">{v.signal}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground">当前接口返回 T 日持仓摘要；T+1 预测成功率需后端按时间顺序积累指数历史后计算，尚未有样本时不显示虚构胜率。</p></div>}</>;
}

function EtfPanel({ date }: { date: string }) {
  const [rows, setRows] = useState<EtfShareRow[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const load = async (refresh = false) => { setBusy(true); setError(""); try { if (refresh) await api.etfSync(date); setRows(await api.etfHistory(date, date)); } catch (e) { setError(e instanceof ApiError ? e.message : "ETF 份额加载失败"); } finally { setBusy(false); } };
  useEffect(() => { void load(false); }, [date]);
  const groups = useMemo(() => Object.entries(rows.reduce<Record<string, number>>((a, r) => { const k = r.category || "未分类"; a[k] = (a[k] || 0) + (r.share_change || 0); return a; }, {})).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 20), [rows]);
  const chart = { tooltip: { trigger: "axis" }, xAxis: { type: "category", data: groups.map(([k]) => k) }, yAxis: { type: "value", name: "份额变化" }, series: [{ type: "bar", data: groups.map(([, v]) => v) }] };
  return <><div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">ETF 份额分析</h2><p className="text-xs text-muted-foreground">份额变化不等同资金流；估算资金流仅在公开净值/收盘价可用时计算。</p></div><button onClick={() => void load(true)} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50"><RefreshCw className={busy ? "h-4 w-4 animate-spin" : "h-4 w-4"} />拉取当日</button></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!rows.length ? <Empty message="暂无已保存的 ETF 份额数据。点击‘拉取当日’请求配置的真实公开源。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={320} /></div><div className="rounded-xl border border-border p-4 text-sm">已保存 {rows.length} 只 ETF；估算资金流合计：{fmt(rows.reduce((s, r) => s + (r.estimated_net_flow || 0), 0))}</div></div>}</>;
}

function NationalPanel({ date }: { date: string }) {
  const [data, setData] = useState<NationalTeamSummary | null>(null); const [error, setError] = useState("");
  useEffect(() => { api.nationalTeamSummary(date).then(setData).catch(e => setError(e instanceof ApiError ? e.message : "宽基代理数据加载失败")); }, [date]);
  const groups = Object.entries(data?.groups || {}); const chart = { tooltip: { trigger: "axis" }, xAxis: { type: "category", data: groups.map(([k]) => k) }, yAxis: { type: "value", name: "估算资金流" }, series: [{ type: "bar", data: groups.map(([, v]) => v.estimated_net_flow) }] };
  return <><div className="mb-4"><h2 className="text-lg font-semibold">宽基 ETF “国家队”代理</h2><p className="text-xs text-muted-foreground">仅依据公开 ETF 份额变化推断宽基行为，不能证明国家队真实账户交易或主体身份。</p></div>{error && <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}{!groups.length ? <Empty message="暂无该日期的宽基份额数据；请先在 ETF 份额页拉取并保存真实数据。" /> : <div className="space-y-4"><div className="rounded-xl border border-border bg-card p-3"><EChart option={chart} height={300} /></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{groups.map(([name, v]) => <div className="rounded-xl border border-border p-4" key={name}><div className="text-sm font-medium">{name}</div><div className="mt-2 text-lg">{fmt(v.estimated_net_flow)}</div><div className="text-xs text-muted-foreground">份额变化 {fmt(v.share_change)} · ETF 数 {v.funds}</div></div>)}</div></div>}</>;
}

export function MarketStructure() {
  const { tab = "cffex" } = useParams<{ tab: Tab }>(); const navigate = useNavigate(); const active = tabs.some(t => t.key === tab) ? tab as Tab : "cffex"; const [date, setDate] = useState(isoDate());
  return <div className="space-y-5"><div><div className="flex items-center gap-2"><Database className="h-5 w-5 text-primary" /><h1 className="text-2xl font-bold">市场结构</h1></div><p className="mt-1 text-sm text-muted-foreground">中金所多空、ETF 份额与宽基代理的可追溯研究工作台。</p></div><div className="flex flex-wrap gap-2 rounded-xl border border-border bg-card p-2">{tabs.map(t => <button key={t.key} onClick={() => navigate("/market-structure/" + t.key)} className={"rounded-lg px-3 py-2 text-left text-sm " + (active === t.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted/50")}><span className="block font-medium">{t.label}</span><span className="text-[11px] opacity-80">{t.desc}</span></button>)}<label className="ml-auto flex items-center gap-2 px-2 text-sm text-muted-foreground">日期<input type="date" value={date} onChange={e => setDate(e.target.value)} className="rounded-md border border-border bg-background px-2 py-1 text-foreground" /></label></div>{active === "cffex" && <CffexPanel date={date} />}{active === "etf-flow" && <EtfPanel date={date} />}{active === "national-team" && <NationalPanel date={date} />}<div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-muted-foreground"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />所有信号均为公开数据分析或代理推断，不构成投资建议；数据源异常时请以“无数据”为准。</div></div>;
}
