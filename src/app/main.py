"""STOCKWISE: bộ lọc và xếp hạng cổ phiếu HOSE theo động lượng, thanh khoản, dòng tiền khối ngoại.

Chạy:  streamlit run src/app/main.py
Giao diện chỉ ĐỌC từ SQLite (do bộ thu thập ghi), không gọi API khi người dùng thao tác.
"""
from __future__ import annotations
import subprocess
import csv
import io
import sys
from pathlib import Path

# Cho phép `streamlit run src/app/main.py` từ thư mục gốc của project.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app import components, services  # noqa: E402
from src.data import storage  # noqa: E402
from src.finance import sensitivity  # noqa: E402
from src.finance.factors import REASON_LABELS, compute_factors  # noqa: E402
from src.finance.run_ranking import _load_cfg  # noqa: E402

CONFIG_PATH = str(ROOT / "config" / "settings.yaml")

st.set_page_config(page_title="STOCKWISE", page_icon="📈", layout="wide")
components.inject_css()


# ------------------------------------------------------------------ nạp dữ liệu (có cache)
def _db_path(cfg: dict) -> Path:
    p = Path(cfg["collect"]["db_path"])
    return p if p.is_absolute() else ROOT / p


def _mtime(path: Path) -> float:
    """Mốc cập nhật của CSDL. SQLite ở chế độ WAL ghi vào file -wal trước nên phải xét cả hai file."""
    files = [path, path.with_name(path.name + "-wal")]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


@st.cache_data(show_spinner=False)
def cached_ranking(db: str, mtime: float, as_of: str, window: int, min_value: float,
                   weights: tuple):
    """Tính xếp hạng một lần cho mỗi bộ tham số; mtime làm cache mất hiệu lực khi DB được cập nhật."""
    _, fc = _load_cfg(CONFIG_PATH)
    conn = storage.connect(db)
    try:
        return services.build_ranking(conn, services.make_factor_config(fc, window, min_value),
                                      weights, as_of)
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def cached_history(db: str, mtime: float, symbol: str):
    conn = storage.connect(db)
    try:
        return services.price_history(conn, symbol)
    finally:
        conn.close()


@st.cache_data(show_spinner="Đang tính độ nhạy…")
def cached_sensitivity(db: str, mtime: float, as_of: str, window: int, min_value: float):
    _, fc = _load_cfg(CONFIG_PATH)
    fc = services.make_factor_config(fc, window, min_value)
    conn = storage.connect(db)
    try:
        items, _ = compute_factors(conn, as_of=as_of, cfg=fc)
        return (sensitivity.weight_sensitivity(items),
                sensitivity.window_sensitivity(conn, fc),
                sensitivity.threshold_sensitivity(conn, fc))
    finally:
        conn.close()


def to_csv(table: list[dict]) -> bytes:
    """CSV có BOM (utf-8-sig) để Excel hiển thị đúng tiếng Việt."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(table[0]))
    w.writeheader()
    w.writerows(table)
    return buf.getvalue().encode("utf-8-sig")


def _tone_style(v) -> str:
    if v is None or v == 0:
        return ""
    return f"color:{components.UP if v > 0 else components.DOWN};font-weight:600"


def styled_table(table: list[dict]):
    df = pd.DataFrame(table)
    return (df.style
            .map(_tone_style, subset=["Sinh lời (%)", "Mua ròng NN (%GT)"])
            .format({"Sinh lời (%)": "{:+.2f}%", "Mua ròng NN (%GT)": "{:+.2f}%",
                     "GT khớp TB (tỷ/phiên)": "{:,.2f}"}))


# ------------------------------------------------------------------ khởi tạo
try:
    cfg, fc_base = _load_cfg(CONFIG_PATH)
except (OSError, KeyError, ValueError) as exc:
    st.error(f"Không đọc được cấu hình `{CONFIG_PATH}`: {exc}")
    st.stop()


db_file = _db_path(cfg)

# ------------------------------------------------------------
# Đầu trang: tiêu đề (điền sau khi biết trạng thái) và nút cập nhật
title_col, btn_col = st.columns([5, 1.4], vertical_alignment="center")
title_slot = title_col.empty()
with btn_col:
    update_clicked = st.button("Cập nhật dữ liệu từ SSI", type="primary")

# ------------------------------------------------------------
# Cập nhật dữ liệu từ SSI
if update_clicked:

    with st.spinner("Đang thu thập dữ liệu từ SSI... Vui lòng chờ."):

        try:
            result = subprocess.run(
                [sys.executable, "-m", "src.data.collector"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            # Gộp log stdout và stderr để hiển thị
            output = "\n".join(
                part for part in [result.stdout, result.stderr]
                if part and part.strip()
            )

            if output:
                with st.expander("Chi tiết quá trình thu thập", expanded=False):
                    st.code(output)

            if result.returncode == 0:
                st.success("Cập nhật dữ liệu SSI hoàn tất!")

            else:
                st.warning(
                    "Quá trình thu thập chưa hoàn tất. "
                    "Có thể đã dừng do quota hoặc lỗi xác thực. "
                    "Hãy kiểm tra log bên trên."
                )

            # Xóa cache để dashboard đọc lại dữ liệu SQLite mới nhất
            st.cache_data.clear()

        except OSError as exc:
            st.error(f"Không thể khởi chạy collector: {exc}")

# ------------------------------------------------------------
# Kiểm tra database
if not db_file.exists():
    st.error(
        f"Chưa có cơ sở dữ liệu `{db_file}`. "
        "Hãy nhấn nút cập nhật dữ liệu từ SSI."
    )
    st.stop()


conn0 = storage.connect(str(db_file))
status = services.get_status(conn0)
dates = services.available_dates(conn0)
wmax_by_date = {d: services.max_window(conn0, d) for d in dates}
conn0.close()

with title_slot.container():
    components.header(status)
components.status_banner(status)
if status.level == "error":
    st.stop()
if not dates:
    st.warning("Chưa đủ dữ liệu: cần ít nhất 6 phiên giao dịch để xếp hạng. Hãy chạy thêm bộ thu thập.")
    st.stop()

DB, MT = str(db_file), _mtime(db_file)

# ------------------------------------------------------------------ thanh bên: bộ lọc và trọng số
with st.sidebar:
    st.header("⚙️ Thiết lập")
    as_of = st.selectbox("Ngày đánh giá", dates, index=0)
    wmax = wmax_by_date[as_of]
    windows = [w for w in (5, 10, 20) if w <= wmax] or [5]
    window = st.radio("Cửa sổ phân tích (phiên)", windows, horizontal=True)
    thr_options = {"0,5 tỷ": 0.5e9, "1 tỷ": 1e9, "2 tỷ": 2e9}
    default_thr = min(thr_options, key=lambda k: abs(thr_options[k] - fc_base.min_avg_value))
    thr_label = st.selectbox("Thanh khoản tối thiểu (GT khớp TB/phiên)", list(thr_options),
                             index=list(thr_options).index(default_thr))
    min_value = thr_options[thr_label]

    st.subheader("Trọng số")
    mode = st.radio("Bộ trọng số", ["Bằng nhau", "Tùy chỉnh"], horizontal=True)
    m = l = f = 0.0
    if mode == "Tùy chỉnh":
        m = st.slider("Động lượng (%)", 0, 100, 50, 5)
        l = st.slider("Thanh khoản (%)", 0, 100, 30, 5)
        f = st.slider("Khối ngoại (%)", 0, 100, 20, 5)
        total = m + l + f
        (st.success if total == 100 else st.error)(f"Tổng trọng số: {total:g}% (cần đúng 100%)")
    weights, w_err = services.parse_weights("equal" if mode == "Bằng nhau" else "custom", m, l, f)
    st.divider()
    st.caption(components.DISCLAIMER)

if w_err:
    st.error(w_err + " Hãy chỉnh lại các thanh trượt.")
    st.stop()

with title_slot.container():
    wlabel = "trọng số bằng nhau" if mode == "Bằng nhau" else f"trọng số {m:g}/{l:g}/{f:g}"
    components.header(status, f"Phiên {as_of} · cửa sổ {window} phiên · {wlabel}")

try:
    items, rep, rows = cached_ranking(DB, MT, as_of, window, min_value, weights)
except ValueError as exc:
    st.error(f"Chưa thể xếp hạng với thiết lập này: {exc}. Thử giảm cửa sổ hoặc hạ ngưỡng thanh khoản.")
    st.stop()

tab_rank, tab_detail, tab_sens, tab_method = st.tabs(
    ["🏆 Xếp hạng", "🔎 Chi tiết mã", "🧪 Độ nhạy", "📘 Phương pháp và giới hạn"])

# ------------------------------------------------------------------ tab 1: xếp hạng
with tab_rank:
    met = services.summary_metrics(items, rows)
    breadth = met["pct_positive_momentum"]
    low_liq = services.reason_counts(items).get("Thanh khoản dưới ngưỡng", 0)
    if len(rows) >= 3:
        components.top_row(rows, met, low_liq)
    st.caption(f"Phạm vi: {', '.join(rep['boards'])} · ngày đánh giá {rep['as_of']} · "
               f"cửa sổ {rep['window_dates'][0]} → {rep['window_dates'][-1]} · "
               f"điểm trung vị {met['median_score']:.1f}")
    left, right = st.columns([1.7, 1])
    with left:
        components.contribution_panel(services.contributions(rows, weights, 8),
                                      "Top 8: đóng góp của từng yếu tố vào điểm tổng")
    with right:
        components.side_cards([
            components.kpi("Độ rộng thị trường", f"{breadth:.0f}%", f"mã tăng giá trong {window} phiên",
                           "up" if breadth >= 50 else "down"),
            components.kpi("Khối ngoại mua/bán ròng", f"{met['net_foreign_bn']:+,.0f} tỷ",
                           "mỗi phiên, tổng rổ đủ điều kiện", components.tone_of(met["net_foreign_bn"])),
            components.kpi("GT khớp TB của rổ", f"{met['avg_value_total_bn']:,.0f} tỷ", "mỗi phiên"),
        ])

    components.section("Bảng xếp hạng", "Điểm 0–100 là thứ hạng tương đối trong rổ đủ điều kiện")
    f1, f2 = st.columns([2, 1])
    query = f1.text_input("Tìm mã", "", placeholder="Ví dụ: VCB")
    max_top = max(len(rows), 6)
    top = f2.slider("Hiển thị top", 5, max_top, min(30, max_top))
    table = services.rows_to_table(rows, query, top)
    if table:
        st.dataframe(
            styled_table(table), hide_index=True, height=min(38 * len(table) + 40, 640),
            column_config={
                "Điểm": st.column_config.ProgressColumn("Điểm", min_value=0, max_value=100, format="%.1f"),
                "Động lượng": st.column_config.ProgressColumn("Động lượng", min_value=0, max_value=100, format="%.0f"),
                "Thanh khoản": st.column_config.ProgressColumn("Thanh khoản", min_value=0, max_value=100, format="%.0f"),
                "Khối ngoại": st.column_config.ProgressColumn("Khối ngoại", min_value=0, max_value=100, format="%.0f"),
            })
        st.download_button("⬇️ Tải bảng xếp hạng (CSV)", data=to_csv(table),
                           file_name=f"stockwise_{rep['as_of']}.csv", mime="text/csv")
    else:
        st.info("Không có mã nào khớp từ khóa tìm kiếm.")

    c1, c2 = st.columns(2)
    c1.plotly_chart(components.market_map(rows))
    c2.plotly_chart(components.reason_donut(services.reason_counts(items)))
    c3, c4 = st.columns([3, 2])
    c3.plotly_chart(components.score_heatmap(rows, 20))
    c4.plotly_chart(components.contribution_bar(
        services.contributions(rows, weights, 10), "Top 10: đóng góp của từng yếu tố"))

    with st.expander(f"Mã bị loại khỏi xếp hạng ({met['n_total'] - met['n_eligible']}) và lý do"):
        st.write(services.reason_counts(items))
        st.dataframe(services.excluded_table(items), hide_index=True)

# ------------------------------------------------------------------ tab 2: chi tiết mã
with tab_detail:
    ranked = {r["symbol"]: r for r in rows}
    options = [r["symbol"] for r in rows] + [it["symbol"] for it in items if not it["eligible"]]
    symbol = st.selectbox("Chọn mã", options, index=0)
    if symbol in ranked:
        r = ranked[symbol]
        components.symbol_card(r, len(rows))
        st.write("")
        components.kpi_row([
            components.kpi(f"Sinh lời {window} phiên", f"{r['momentum'] * 100:+.2f}%",
                           tone=components.tone_of(r["momentum"]), icon="📈"),
            components.kpi("GT khớp TB", f"{r['avg_value'] / 1e9:,.2f} tỷ", "mỗi phiên", icon="💧"),
            components.kpi("Mua ròng NN", f"{r['foreign_ratio'] * 100:+.2f}%", "% giá trị khớp",
                           components.tone_of(r["foreign_ratio"]), "🌐"),
        ])
        st.write("")
        left, right = st.columns(2)
        left.plotly_chart(components.radar(symbol, {
            services.FACTOR_LABELS[k]: r[k] for k in services.SCORE_KEYS}))
        hist = cached_history(DB, MT, symbol)
        if hist:
            right.plotly_chart(components.price_chart(hist, symbol))
        else:
            right.info("Chưa có dữ liệu giá cho mã này.")
        if hist:
            st.plotly_chart(components.foreign_flow_chart(hist, symbol))
        components.note(services.explain(r, len(rows)))
    else:
        it = next(i for i in items if i["symbol"] == symbol)
        st.warning(f"{symbol} không được xếp hạng: {REASON_LABELS.get(it['reason'], it['reason'])}.")
        hist = cached_history(DB, MT, symbol)
        if hist:
            st.plotly_chart(components.price_chart(hist, symbol))

# ------------------------------------------------------------------ tab 3: độ nhạy
with tab_sens:
    st.write("Mức độ thay đổi của thứ hạng khi đổi trọng số, cửa sổ hoặc ngưỡng thanh khoản "
             "(hệ số Spearman, càng gần 1 càng ổn định).")
    try:
        (wn, wm), (cn, cm), thr_rows = cached_sensitivity(DB, MT, as_of, window, min_value)
        s1, s2 = st.columns(2)
        s1.plotly_chart(components.heatmap(wn, wm, "Theo bộ trọng số"))
        if cn:
            s2.plotly_chart(components.heatmap(cn, cm, "Theo cửa sổ (trọng số bằng nhau)"))
        components.section("Theo ngưỡng thanh khoản")
        st.dataframe([{"Ngưỡng (tỷ)": thr / 1e9, "Số mã đủ điều kiện": n,
                       "Spearman": None if c["spearman"] is None else round(c["spearman"], 3),
                       f"Trùng top {c['top_n']}": f"{c['top_overlap']}/{c['top_n']}"}
                      for thr, n, c in thr_rows], hide_index=True)
        st.caption("Độ nhạy theo cửa sổ và theo ngưỡng được tính tại phiên mới nhất; "
                   "độ nhạy theo trọng số tính tại ngày đánh giá đang chọn.")
        st.caption("Các bộ trọng số dùng chung ba thành phần nên hệ số cao một phần do cách xây dựng, "
                   "không phải bằng chứng mô hình đúng.")
    except ValueError as exc:
        st.warning(f"Chưa đủ dữ liệu để phân tích độ nhạy: {exc}")

# ------------------------------------------------------------------ tab 4: phương pháp
with tab_method:
    st.subheader("Cách tính")
    st.markdown(f"Cửa sổ N = **{window}** phiên giao dịch gần nhất của thị trường (lịch lấy từ dữ liệu).")
    st.latex(r"\text{Momentum}=\frac{P_t}{P_{t-N}}-1")
    st.latex(r"\text{Liquidity}=\frac{1}{N}\sum_{k=0}^{N-1}\text{GTkhớp}_{t-k}")
    st.latex(r"\text{ForeignFlow}=\frac{\sum(\text{Mua NN}-\text{Bán NN})}{\sum \text{GTkhớp}}")
    st.latex(r"\text{Pct}=\frac{\text{rank}-1}{n-1}\times 100,\qquad "
             r"\text{Score}=\sum_f w_f\,\text{Pct}_f,\ \ \sum_f w_f=100\%")
    st.markdown(
        "- Cả ba yếu tố đều *càng cao càng tốt*; đồng hạng nhận phân vị trung bình.\n"
        "- Phiên không giao dịch tính 0 đồng thanh khoản (SSI chỉ trả bản ghi cho phiên có khớp lệnh).\n"
        f"- Điều kiện xếp hạng: GT khớp TB ≥ {min_value / 1e9:g} tỷ/phiên, giao dịch ≥ "
        f"{services.make_factor_config(fc_base, window, min_value).min_traded_sessions}/{window} phiên, "
        "đủ lịch sử, không có biến động giá liền kề vượt biên độ (nghi điều chỉnh giá).")
    st.subheader("Giới hạn")
    st.markdown(
        "- **Phạm vi:** chỉ cổ phiếu HOSE, không phải toàn thị trường. Khối ngoại có giao dịch ở "
        "khoảng 62% bản ghi HOSE, ít hơn nhiều ở HNX/UPCOM nên đề tài giới hạn ở HOSE.\n"
        f"- **Dữ liệu ngắn:** {status.n_sessions} phiên; dữ liệu theo ngày, không có nội ngày.\n"
        "- **Chưa kiểm chứng khả năng dự báo:** không có backtest; không dùng để suy ra lợi nhuận.\n"
        "- **Thanh khoản:** dùng GT khớp để đo khả năng giao dịch, khác với phần bù phi thanh khoản "
        "của Amihud (2002).\n"
        "- **Percentile rank** bỏ qua độ lớn chênh lệch giữa các mã.\n"
        "- **Giá điều chỉnh:** chưa xác nhận giá SSI đã điều chỉnh cổ tức/chia tách; mã có biến động "
        "bất thường bị loại.")
    st.warning(components.DISCLAIMER)