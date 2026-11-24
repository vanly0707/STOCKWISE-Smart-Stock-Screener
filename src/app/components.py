"""Giao diện STOCKWISE: CSS, thẻ HTML và biểu đồ Plotly (không chứa logic dữ liệu)."""
from __future__ import annotations

import html
import math

import plotly.graph_objects as go
import streamlit as st

from .services import FACTOR_LABELS, DataStatus

COLORS = {"Động lượng": "#6366F1", "Thanh khoản": "#14B8A6", "Khối ngoại": "#F59E0B"}
UP, DOWN, ACCENT = "#16A34A", "#DC2626", "#0F9D82"
FONT = "Inter, Segoe UI, system-ui, sans-serif"
GRID = "rgba(128,128,128,.18)"
RANK_COLORS = ("#F59E0B", "#94A3B8", "#B45309")   # vàng, bạc, đồng
MEDALS = ("🥇", "🥈", "🥉")

DISCLAIMER = ("STOCKWISE là công cụ phân tích học thuật, không phải khuyến nghị đầu tư. "
              "Điểm số là xếp hạng tương đối, không dự báo lợi nhuận.")

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.block-container{
    padding-top:4rem !important;
    max-width:1320px;
}
#MainMenu,footer{visibility:hidden}
.sw-hero,.sw-card,.sw-sec,.sw-note,h1,h2,h3,h4{font-family:'Inter','Segoe UI',system-ui,sans-serif}

/* ---- hero */
.sw-hero{position:relative;overflow:hidden;padding:1.7rem 2rem;border-radius:22px;margin-bottom:1.2rem;color:#fff;
  background:linear-gradient(120deg,#0f766e 0%,#0e7490 50%,#4338ca 100%);box-shadow:0 14px 34px rgba(14,116,144,.28)}
.sw-hero:before{content:"";position:absolute;right:-70px;top:-90px;width:320px;height:320px;border-radius:50%;background:rgba(255,255,255,.10)}
.sw-hero:after{content:"";position:absolute;right:170px;bottom:-130px;width:240px;height:240px;border-radius:50%;background:rgba(255,255,255,.07)}
.sw-hero>*{position:relative;z-index:1}
.sw-hero h1{margin:0;font-size:2.2rem;font-weight:800;letter-spacing:-.03em;color:#fff;padding:0}
.sw-hero p{margin:.4rem 0 .9rem;opacity:.93;font-size:1rem;max-width:820px;line-height:1.55}
.sw-chip{display:inline-block;padding:.22rem .8rem;margin:0 .4rem .35rem 0;border-radius:999px;font-size:.8rem;
  background:rgba(255,255,255,.17);border:1px solid rgba(255,255,255,.22);backdrop-filter:blur(4px)}

/* ---- thẻ */
.sw-card{border:1px solid rgba(15,23,42,.07);border-radius:16px;padding:.95rem 1.15rem;background:#fff;height:100%;
  box-shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.06);transition:transform .15s,box-shadow .15s}
.sw-card:hover{transform:translateY(-2px);box-shadow:0 2px 4px rgba(15,23,42,.05),0 14px 30px rgba(15,23,42,.10)}
.sw-card .lbl{font-size:.72rem;opacity:.6;text-transform:uppercase;letter-spacing:.07em;font-weight:600}
.sw-card .val{font-size:1.75rem;font-weight:800;line-height:1.25;margin-top:.15rem;letter-spacing:-.02em}
.sw-card .sub{font-size:.8rem;opacity:.65;margin-top:.1rem}
.sw-kpi{position:relative;overflow:hidden;padding-left:1.35rem}
.sw-kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--c,#0F9D82)}
.sw-kpi .ic{position:absolute;right:14px;top:10px;font-size:1.5rem;opacity:.9}
.up{color:#16A34A}.down{color:#DC2626}

/* ---- tiêu đề mục */
.sw-sec{margin:1.5rem 0 .6rem}
.sw-sec h3{margin:0;padding:0 0 0 .8rem;font-size:1.25rem;font-weight:700;border-left:5px solid #0F9D82;line-height:1.3}
.sw-sec p{margin:.15rem 0 0 1.05rem;font-size:.85rem;opacity:.65}

/* ---- podium, thanh yếu tố, vòng điểm */
.sw-pod{border-top:5px solid var(--c)}
.sw-pod .sym{font-size:2rem;font-weight:800;letter-spacing:.01em;line-height:1.1}
.sw-pod .score{font-size:1.15rem;font-weight:800;color:#0F9D82;margin-bottom:.3rem}
.sw-pod .score span{font-size:.8rem;font-weight:500;opacity:.7}
.sw-bar{display:flex;align-items:center;gap:.55rem;font-size:.76rem;margin-top:.32rem}
.sw-bar span{width:74px;opacity:.7}.sw-bar b{width:26px;text-align:right}
.sw-trk{flex:1;height:7px;border-radius:99px;background:rgba(128,128,128,.18)}
.sw-trk i{display:block;height:100%;border-radius:99px}
.sw-sym{display:flex;gap:1.6rem;align-items:center;flex-wrap:wrap}
.sw-sym .mid{min-width:150px}
.sw-sym .sym{font-size:2.3rem;font-weight:800;line-height:1.1}
.sw-sym .bars{flex:1;min-width:240px}
.sw-ring{width:92px;height:92px;border-radius:50%;display:grid;place-items:center;flex:none;
  background:conic-gradient(#0F9D82 calc(var(--p)*1%),rgba(128,128,128,.18) 0)}
.sw-ring span{width:72px;height:72px;border-radius:50%;background:#fff;display:grid;place-items:center;font-weight:800;font-size:1.45rem}

.sw-note{border-left:4px solid #0F9D82;border-radius:10px;padding:.9rem 1.1rem;background:rgba(15,157,130,.08);line-height:1.65;margin-top:.8rem}
[data-testid="stTabs"] button[role="tab"]{font-size:1rem;font-weight:600;padding:.6rem 1rem}
[data-testid="stSidebar"]{border-right:1px solid rgba(15,23,42,.07)}
[data-testid="stPlotlyChart"]{background:#fff;border:1px solid rgba(15,23,42,.07);border-radius:16px;padding:.4rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.05)}
@media (prefers-color-scheme: dark){
  .sw-card,.sw-ring span,[data-testid="stPlotlyChart"]{background:rgba(255,255,255,.05)}
  .sw-card,[data-testid="stPlotlyChart"]{border-color:rgba(255,255,255,.1)}
}

/* ---- nút Streamlit */
[data-testid="stButton"] > button {
  min-height: 44px !important;
  height: auto !important;
  padding: 0.65rem 1.2rem !important;
  line-height: 1.4 !important;
  white-space: nowrap !important;
  overflow: visible !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

[data-testid="stButton"] > button p {
  margin: 0 !important;
  line-height: 1.4 !important;
  visibility: visible !important;
}
/* ---- Giao diện C: nền xám nhạt, sidebar tối, thẻ bo tròn */
[data-testid="stAppViewContainer"]{background:#EEF2F6}
[data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"]{background:#0F172A;border-right:none}
[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] label p,[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#E2E8F0 !important}
.sw-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:.2rem 0 .8rem}
.sw-head .t{font-size:1.65rem;font-weight:800;letter-spacing:-.02em;color:#0F172A;line-height:1.2}
.sw-head .s{font-size:.85rem;color:#475569}
.sw-pill{display:inline-block;padding:.28rem .85rem;border-radius:999px;font-size:.78rem;font-weight:700;margin:.4rem .4rem 0 0}
.sw-pill.ok{background:#DCFCE7;color:#166534}.sw-pill.warn{background:#FEF3C7;color:#92400E}
.sw-pill.err{background:#FEE2E2;color:#991B1B}.sw-pill.info{background:#E2E8F0;color:#334155;font-weight:600}
.sw-pod .lbl{opacity:1;color:#475569}
.sw-donut{display:flex;align-items:center;gap:1rem}
.sw-donut .ring{width:84px;height:84px;border-radius:50%;display:grid;place-items:center;flex:none;
  background:conic-gradient(#0F766E calc(var(--p)*1%),#E2E8F0 0)}
.sw-donut .ring span{width:62px;height:62px;border-radius:50%;background:#fff;display:grid;place-items:center;font-weight:800;font-size:1.1rem;color:#0F172A}
.sw-panel{border-radius:20px;padding:1.2rem 1.35rem;background:#fff;box-shadow:0 8px 24px rgba(15,23,42,.07)}
.sw-panel h4{margin:0 0 .7rem;font-size:1rem;font-weight:700;padding:0;color:#0F172A}
.sw-crow{display:flex;align-items:center;gap:.75rem;font-size:.82rem;margin-top:.4rem;color:#0F172A}
.sw-crow b.s{width:46px}.sw-crow b.v{width:46px;text-align:right;color:#0F766E}
.sw-cbar{flex:1;display:flex;height:22px;border-radius:6px;overflow:hidden;background:#F1F5F9}
.sw-cbar i{display:block;height:100%}
.sw-legend{display:flex;gap:1.1rem;margin-top:.9rem;font-size:.75rem;color:#475569}
.sw-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}
.sw-stack{display:flex;flex-direction:column;gap:1rem}
.sw-card,.sw-card .val,.sw-card .sym{color:#0F172A}
.sw-card .lbl,.sw-card .sub{color:#475569;opacity:1}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def tone_of(x: float) -> str:
    return "up" if x > 0 else "down" if x < 0 else ""


# ---------------------------------------------------------------- thẻ HTML
def header(status: DataStatus, subtitle: str = "") -> None:
    """Đầu trang: tiêu đề, dòng phụ và các nhãn trạng thái dữ liệu."""
    pill = {"ok": ("ok", "Dữ liệu ổn định"), "warn": ("warn", "Dữ liệu cần chú ý")}.get(
        status.level, ("err", "Chưa có dữ liệu"))
    chips = [f'<span class="sw-pill {pill[0]}">{pill[1]}</span>']
    if status.last_date:
        chips.append(f'<span class="sw-pill info">HOSE · {status.n_sessions} phiên · đến {html.escape(status.last_date)}</span>')
    if status.last_run_at:
        chips.append('<span class="sw-pill info">Thu thập '
                     + html.escape(status.last_run_at[:16].replace("T", " ")) + " (UTC+7)</span>")
    st.markdown(
        '<div class="sw-head"><div><div class="t">STOCKWISE · Xếp hạng cổ phiếu HOSE</div>'
        f'<div class="s">{html.escape(subtitle or "Bộ lọc và xếp hạng theo động lượng, thanh khoản, khối ngoại")}</div>'
        f'<div>{"".join(chips)}</div></div></div>', unsafe_allow_html=True)


def top_row(rows: list[dict], met: dict, low_liquidity: int) -> None:
    """Hàng đầu: ba thẻ top 3 và thẻ tỷ lệ mã đủ điều kiện (dạng vòng)."""
    cols = st.columns(4)
    for col, r, medal, color in zip(cols[:3], rows[:3], ("HẠNG 1", "HẠNG 2", "HẠNG 3"), RANK_COLORS):
        col.markdown(
            f'<div class="sw-card sw-pod" style="--c:{color}"><div class="lbl">{medal}</div>'
            f'<div class="sym">{html.escape(r["symbol"])}</div>'
            f'<div class="score">{r["score"]:.1f}<span> điểm</span></div>'
            f'<div class="sub"><b class="{tone_of(r["momentum"])}">{r["momentum"] * 100:+.2f}%</b>'
            f' · {r["avg_value"] / 1e9:,.1f} tỷ/phiên</div></div>', unsafe_allow_html=True)
    cols[3].markdown(
        f'<div class="sw-card sw-donut"><div class="ring" style="--p:{met["pct_eligible"]:.1f}">'
        f'<span>{met["pct_eligible"]:.0f}%</span></div><div><div class="lbl">Mã đủ điều kiện</div>'
        f'<div class="val">{met["n_eligible"]}<span style="font-size:.9rem;font-weight:500"> / {met["n_total"]}</span></div>'
        f'<div class="sub">{low_liquidity} mã loại vì thanh khoản thấp</div></div></div>',
        unsafe_allow_html=True)


def contribution_panel(data: list[dict], title: str) -> None:
    """Cột chồng bằng HTML: mỗi yếu tố đóng góp bao nhiêu điểm vào điểm tổng (độ rộng = điểm đóng góp)."""
    out = []
    for d in data:
        segs = "".join(f'<i style="width:{d[label]:.2f}%;background:{COLORS[label]}" '
                       f'title="{label}: {d[label]:.1f}"></i>' for label in FACTOR_LABELS.values())
        total = sum(d[label] for label in FACTOR_LABELS.values())
        out.append(f'<div class="sw-crow"><b class="s">{html.escape(d["Mã"])}</b>'
                   f'<div class="sw-cbar">{segs}</div><b class="v">{total:.1f}</b></div>')
    legend = "".join(f'<span><i style="background:{c}"></i>{k}</span>' for k, c in COLORS.items())
    st.markdown(f'<div class="sw-panel"><h4>{html.escape(title)}</h4>{"".join(out)}'
                f'<div class="sw-legend">{legend}</div></div>', unsafe_allow_html=True)


def side_cards(cards: list[str]) -> None:
    st.markdown('<div class="sw-stack">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def hero(status: DataStatus) -> None:
    dot = {"ok": "🟢 Dữ liệu ổn định", "warn": "🟡 Dữ liệu cần chú ý"}.get(status.level, "🔴 Chưa có dữ liệu")
    chips = [dot, "Phạm vi: HOSE", "Nguồn: SSI FastConnect (lưu SQLite)"]
    if status.last_date:
        chips.insert(2, f"Dữ liệu đến {status.last_date}")
        chips.insert(3, f"{status.n_sessions} phiên")
    if status.last_run_at:
        chips.append("Thu thập lần cuối " + status.last_run_at[:16].replace("T", " "))
    st.markdown(
        '<div class="sw-hero"><h1>📈 STOCKWISE</h1>'
        "<p>Bộ lọc và xếp hạng cổ phiếu HOSE minh bạch theo động lượng giá, thanh khoản và "
        "dòng tiền khối ngoại. Dành cho nhà đầu tư cá nhân và sinh viên tài chính cần sàng lọc nhanh; "
        "tự chỉnh trọng số và xem thứ hạng thay đổi ra sao.</p>"
        + "".join(f'<span class="sw-chip">{html.escape(c)}</span>' for c in chips) + "</div>",
        unsafe_allow_html=True)


def status_banner(status: DataStatus) -> None:
    """Chỉ hiện khi dữ liệu có vấn đề; trạng thái tốt đã nằm ở các chip trong hero."""
    if status.level == "error":
        st.error(status.message)
    elif status.level == "warn":
        st.warning(status.message)


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="sw-sec"><h3>{html.escape(title)}</h3>'
                + (f"<p>{html.escape(sub)}</p>" if sub else "") + "</div>", unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", tone: str = "", icon: str = "") -> str:
    color = {"up": UP, "down": DOWN}.get(tone, ACCENT)
    return (f'<div class="sw-card sw-kpi" style="--c:{color}"><div class="ic">{icon}</div>'
            f'<div class="lbl">{html.escape(label)}</div>'
            f'<div class="val {tone}">{html.escape(value)}</div>'
            f'<div class="sub">{html.escape(sub)}</div></div>')


def kpi_row(cards: list[str]) -> None:
    for col, card in zip(st.columns(len(cards)), cards):
        col.markdown(card, unsafe_allow_html=True)


def bars_html(r: dict) -> str:
    """Ba thanh tiến độ điểm thành phần (0-100)."""
    return "".join(
        f'<div class="sw-bar"><span>{label}</span><div class="sw-trk"><i style="width:{r[key]:.0f}%;'
        f'background:{COLORS[label]}"></i></div><b>{r[key]:.0f}</b></div>'
        for key, label in FACTOR_LABELS.items())


def podium(rows: list[dict]) -> None:
    """Ba mã đứng đầu dưới dạng thẻ có viền vàng/bạc/đồng."""
    for col, r, medal, color in zip(st.columns(3), rows[:3], MEDALS, RANK_COLORS):
        col.markdown(
            f'<div class="sw-card sw-pod" style="--c:{color}"><div class="lbl">{medal} Hạng {r["rank"]}</div>'
            f'<div class="sym">{html.escape(r["symbol"])}</div>'
            f'<div class="score">{r["score"]:.1f}<span> điểm</span></div>'
            f'<div class="sub"><b class="{tone_of(r["momentum"])}">{r["momentum"] * 100:+.2f}%</b>'
            f' · {r["avg_value"] / 1e9:,.1f} tỷ/phiên</div>{bars_html(r)}</div>',
            unsafe_allow_html=True)


def symbol_card(r: dict, n_ranked: int) -> None:
    """Thẻ đầu trang chi tiết mã: vòng điểm, thứ hạng và ba thanh yếu tố."""
    st.markdown(
        f'<div class="sw-card sw-sym"><div class="sw-ring" style="--p:{r["score"]:.1f}"><span>{r["score"]:.0f}</span></div>'
        f'<div class="mid"><div class="lbl">Cổ phiếu HOSE</div><div class="sym">{html.escape(r["symbol"])}</div>'
        f'<div class="sub">Hạng <b>{r["rank"]}</b>/{n_ranked} · điểm tổng hợp {r["score"]:.1f}</div></div>'
        f'<div class="bars">{bars_html(r)}</div></div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="sw-note">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- biểu đồ
def _base(fig: go.Figure, height: int, title: str | None = None) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(size=15)) if title else None,
        height=height, font=dict(family=FONT, size=12),
        margin=dict(l=14, r=14, t=52 if title else 18, b=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font_family=FONT), legend=dict(orientation="h", y=-0.18, x=0))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def contribution_bar(data: list[dict], title: str) -> go.Figure:
    """Cột chồng ngang: mỗi yếu tố đóng góp bao nhiêu điểm vào điểm tổng của từng mã."""
    fig = go.Figure()
    symbols = [d["Mã"] for d in data]
    for label in FACTOR_LABELS.values():
        fig.add_bar(name=label, y=symbols, x=[d[label] for d in data], orientation="h",
                    marker_color=COLORS[label],
                    hovertemplate=f"<b>%{{y}}</b><br>{label}: %{{x:.1f}} điểm<extra></extra>")
    fig.update_layout(barmode="stack", bargap=.25, yaxis=dict(autorange="reversed"),
                      xaxis_title="Điểm đóng góp vào điểm tổng")
    return _base(fig, 470, title)


def market_map(rows: list[dict], label_top: int = 12) -> go.Figure:
    """Bản đồ rổ: sinh lời (x) – khối ngoại (y), kích cỡ = thanh khoản, màu = điểm."""
    sizes = [max(8.0, min(40.0, 8 + 4 * math.sqrt(r["avg_value"] / 1e9))) for r in rows]
    fig = go.Figure(go.Scatter(
        x=[r["momentum"] * 100 for r in rows], y=[r["foreign_ratio"] * 100 for r in rows],
        mode="markers+text", text=[r["symbol"] if i < label_top else "" for i, r in enumerate(rows)],
        textposition="top center", textfont=dict(size=11),
        customdata=[[r["symbol"], r["avg_value"] / 1e9, r["score"]] for r in rows],
        marker=dict(size=sizes, color=[r["score"] for r in rows], cmin=0, cmax=100,
                    colorscale=[[0, "#CBD5E1"], [0.5, "#5EEAD4"], [1, ACCENT]],
                    opacity=.85, line=dict(width=1, color="white"),
                    colorbar=dict(title="Điểm", thickness=10, len=.8)),
        hovertemplate=("<b>%{customdata[0]}</b><br>Sinh lời %{x:+.2f}%<br>Mua ròng NN %{y:+.2f}%<br>"
                       "GT khớp %{customdata[1]:,.1f} tỷ/phiên<br>Điểm %{customdata[2]:.1f}<extra></extra>")))
    fig.add_hline(y=0, line_dash="dot", line_color="gray")
    fig.add_vline(x=0, line_dash="dot", line_color="gray")
    fig.update_layout(xaxis_title="Sinh lời trong cửa sổ (%)", yaxis_title="Mua ròng khối ngoại (% GT khớp)")
    return _base(fig, 470, "Bản đồ rổ: kích cỡ = thanh khoản, màu = điểm")


def score_heatmap(rows: list[dict], top: int = 20) -> go.Figure:
    """Bản đồ nhiệt điểm thành phần của top N mã: nhìn ngay mã mạnh/yếu ở yếu tố nào."""
    sel = rows[:top]
    labels = list(FACTOR_LABELS.values())
    z = [[r[k] for k in FACTOR_LABELS] for r in sel]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=[r["symbol"] for r in sel], zmin=0, zmax=100, xgap=3, ygap=3,
        colorscale=[[0, "#F1F5F9"], [0.5, "#99F6E4"], [1, "#0F766E"]], showscale=False,
        text=[[f"{v:.0f}" for v in row] for row in z], texttemplate="%{text}",
        hovertemplate="%{y} · %{x}: %{z:.1f}<extra></extra>"))
    fig.update_layout(yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
    return _base(fig, 470, f"Điểm thành phần của top {len(sel)}")


def reason_donut(counts: dict[str, int]) -> go.Figure:
    """Donut: bao nhiêu mã đủ điều kiện và các lý do loại phần còn lại."""
    labels = list(counts)
    palette = ["#94A3B8", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4", "#64748B"]
    colors, k = [], 0
    for lb in labels:
        if lb == "Đủ điều kiện":
            colors.append(ACCENT)
        else:
            colors.append(palette[k % len(palette)])
            k += 1
    total = sum(counts.values())
    fig = go.Figure(go.Pie(labels=labels, values=list(counts.values()), hole=.62, sort=False,
                           marker=dict(colors=colors, line=dict(color="white", width=2)),
                           textinfo="value", hovertemplate="%{label}: %{value} mã (%{percent})<extra></extra>"))
    fig.update_layout(legend=dict(orientation="v", y=.5, x=1.02),
                      annotations=[dict(text=f"<b>{total}</b><br>mã", x=.5, y=.5, showarrow=False,
                                        font=dict(size=20))])
    return _base(fig, 470, "Mã đủ điều kiện và lý do bị loại")


def radar(symbol: str, scores: dict[str, float]) -> go.Figure:
    """Radar ba điểm thành phần; đường nét đứt là mức 50 (trung vị của percentile rank)."""
    labels = list(scores)
    values = [scores[k] for k in labels]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[50] * (len(labels) + 1), theta=labels + labels[:1], mode="lines",
                                  line=dict(dash="dash", color="gray"), name="Mức 50"))
    fig.add_trace(go.Scatterpolar(r=values + values[:1], theta=labels + labels[:1], fill="toself",
                                  name=symbol, line=dict(color=ACCENT, width=3),
                                  fillcolor="rgba(15,157,130,.25)"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], gridcolor=GRID),
                                 bgcolor="rgba(0,0,0,0)"), showlegend=True)
    return _base(fig, 380, "Ba điểm thành phần (0–100)")


def price_chart(history: list[dict], symbol: str) -> go.Figure:
    """Đường giá đóng cửa (trục trái) và cột giá trị khớp (trục phải)."""
    x = [h["date"] for h in history]
    fig = go.Figure()
    fig.add_bar(x=x, y=[h["value_bn"] for h in history], name="GT khớp (tỷ)",
                marker_color="rgba(148,163,184,.4)", yaxis="y2")
    fig.add_trace(go.Scatter(x=x, y=[h["close"] for h in history], mode="lines+markers",
                             name="Giá đóng cửa (đ)", line=dict(color=ACCENT, width=2.5),
                             marker=dict(size=5)))
    fig.update_layout(yaxis=dict(title="Giá đóng cửa (đồng)"),
                      yaxis2=dict(title="Giá trị khớp (tỷ đồng)", overlaying="y", side="right",
                                  showgrid=False),
                      xaxis=dict(type="category", tickangle=-45, nticks=12))
    return _base(fig, 380, f"{symbol}: giá đóng cửa và giá trị khớp")


def foreign_flow_chart(history: list[dict], symbol: str) -> go.Figure:
    """Mua/bán ròng khối ngoại theo ngày: xanh = mua ròng, đỏ = bán ròng."""
    x = [h["date"] for h in history]
    y = [h["foreign_net_bn"] for h in history]
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=[UP if v >= 0 else DOWN for v in y],
                           hovertemplate="%{x}<br>Ròng %{y:+.2f} tỷ<extra></extra>"))
    fig.update_layout(xaxis=dict(type="category", tickangle=-45, nticks=12), yaxis_title="Tỷ đồng",
                      showlegend=False)
    return _base(fig, 300, f"{symbol}: khối ngoại mua/bán ròng theo ngày")


def heatmap(names: list[str], matrix: list[list[float]], title: str) -> go.Figure:
    """Ma trận Spearman giữa các cấu hình; màu càng đậm càng giống nhau."""
    flat = [v for row in matrix for v in row if v == v]
    zmin = max(-1.0, min(flat) - 0.02) if flat else 0.0
    fig = go.Figure(go.Heatmap(
        z=matrix, x=names, y=names, zmin=zmin, zmax=1, xgap=3, ygap=3,
        colorscale=[[0, "#E6F4F1"], [1, "#0F766E"]], showscale=False,
        text=[[f"{v:.3f}" for v in row] for row in matrix], texttemplate="%{text}",
        hovertemplate="%{y} vs %{x}: %{z:.3f}<extra></extra>"))
    fig.update_layout(yaxis_autorange="reversed")
    return _base(fig, 360, title)