import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
import pandas as pd
from scipy.stats import percentileofscore


def _slope_label(s):
    if s >= 0.8:
        return "Rất cao — F1 cực nhạy với VIN"
    if s >= 0.55:
        return "Cao — F1 bị VIN dẫn dắt rõ"
    if s >= 0.35:
        return "Trung bình — ảnh hưởng vừa phải"
    return "Thấp — VIN ít tác động lên F1"


def _corr_label(c):
    if c >= 0.75:
        return "Rất chặt — đồng pha cao"
    if c >= 0.55:
        return "Chặt — cùng chiều rõ ràng"
    if c >= 0.35:
        return "Lỏng — đồng pha yếu"
    return "Phân kỳ — chạy độc lập"


def render_core(plot_df, plot_weights, full_result_df):
    st.subheader("1) Composite Return & Risk Band")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=plot_df.index, y=plot_df["Composite_Return"], mode="lines", name="Composite", line=dict(color="#2196f3", width=1)))
    fig1.add_trace(go.Scatter(x=plot_df.index, y=plot_df["CVaR_95"], mode="lines", name="CVaR", line=dict(color="rgba(255,0,0,0)"), showlegend=False))
    fig1.add_trace(go.Scatter(x=plot_df.index, y=plot_df["VaR_95"], mode="lines", name="VaR/CVaR Band", fill="tonexty", fillcolor="rgba(244, 67, 54, 0.3)", line=dict(color="#f44336", width=1.5)))
    fig1.update_layout(height=360, template="plotly_white", hovermode="x unified", margin=dict(l=0, r=0, t=20, b=0))
    st.plotly_chart(fig1, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("2) PCA Weights")
        weights_view = plot_weights.copy()

        fig2 = go.Figure()
        for col, color in [("VIC", "#ff9800"), ("VHM", "#4caf50"), ("VRE", "#9c27b0")]:
            fig2.add_trace(
                go.Scatter(
                    x=weights_view.index,
                    y=weights_view[col],
                    mode="lines",
                    name=col,
                    line=dict(color=color, width=1.5),
                    stackgroup="one",
                )
            )
        fig2.update_layout(height=360, template="plotly_white", yaxis=dict(range=[0, 1]), hovermode="x unified", margin=dict(l=0, r=0, t=20, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    with c2:
        st.subheader("3) Correlation & Slope")
        fig3 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
        fig3.add_trace(go.Scatter(x=plot_df.index, y=plot_df["Correlation"], mode="lines", name="Correlation", line=dict(color="#e91e63")), row=1, col=1)
        fig3.add_trace(go.Scatter(x=plot_df.index, y=plot_df["OLS_Slope"], mode="lines", name="Slope (OLS Beta)", line=dict(color="#3f51b5")), row=2, col=1)
        fig3.update_layout(
            height=360,
            template="plotly_white",
            hovermode="x unified",
            margin=dict(l=0, r=0, t=20, b=0),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig3.update_yaxes(title_text="Correlation", row=1, col=1)
        fig3.update_yaxes(title_text="Slope", row=2, col=1)
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Chú thích: Hồng = Correlation | Xanh = Slope (OLS Beta)")

        latest_date = plot_df.index[-1].strftime("%d/%m/%Y")
        latest_slope = float(plot_df["OLS_Slope"].iloc[-1])
        latest_corr = float(plot_df["Correlation"].iloc[-1])
        pct_slope = percentileofscore(full_result_df["OLS_Slope"].dropna(), latest_slope, kind="rank")
        pct_corr = percentileofscore(full_result_df["Correlation"].dropna(), latest_corr, kind="rank")

        st.markdown(f"**📅 Snapshot dữ liệu gần nhất — {latest_date}**")
        sn1, sn2 = st.columns(2)
        sn1.metric("OLS Slope (Beta)", f"{latest_slope:.3f}")
        sn1.caption(f"Percentile: **{pct_slope:.0f}th** | {_slope_label(latest_slope)}")
        sn2.metric("Correlation", f"{latest_corr:.3f}")
        sn2.caption(f"Percentile: **{pct_corr:.0f}th** | {_corr_label(latest_corr)}")

        st.info(
            f"**💡 Ý nghĩa OLS Slope (Beta):**\n\n"
            f"- Slope = `{latest_slope:.2f}` nghĩa là khi composite VIC/VHM/VRE biến động **1%**, "
            f"VN30F1M có xu hướng biến động khoảng **{latest_slope:.2f}%** cùng phiên.\n"
            f"- Slope càng cao: F1 càng nhạy với nhóm VIN.\n"
            f"- Slope càng thấp: F1 đang phản ứng nhiều hơn với nhân tố khác ngoài VIN."
        )


def render_event(re_df, threshold):
    if re_df is None or re_df.empty:
        st.info("Không đủ dữ liệu event study cho ngày t0 đã chọn.")
        return

    counts = re_df["Regime"].value_counts()
    dominant_regime = counts.idxmax()

    color_map = {
        "COUPLING": "#EF5350",
        "ANCHORING": "#FFA726",
        "STATUS QUO": "#9E9E9E",
        "DECOUPLING": "#42A5F5",
        "TÍN HIỆU GIẢ": "#AB47BC",
    }

    st.markdown("##### 📊 Thống kê Phân bổ Dòng tiền Realtime")
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("⏱️ TỔNG PHIÊN REALTIME", f"{len(re_df)} ngày")
    col_m2.metric("🔗 COUPLING — Siết chặt", f"{counts.get('COUPLING', 0)} ngày")
    col_m3.metric("⚠️ TÍN HIỆU GIẢ — Bẫy nhiễu", f"{counts.get('TÍN HIỆU GIẢ', 0)} ngày")

    col_m4, col_m5, col_m6 = st.columns(3)
    col_m4.metric("⚓ ANCHORING — Neo giữ", f"{counts.get('ANCHORING', 0)} ngày")
    col_m5.metric("🧊 DECOUPLING — Rời bỏ", f"{counts.get('DECOUPLING', 0)} ngày")
    col_m6.metric("➖ STATUS QUO — Quán tính", f"{counts.get('STATUS QUO', 0)} ngày")

    regime_conclusion = {
        "COUPLING": "**COUPLING — Siết chặt:** VIN là hoa tiêu dẫn đường tuyệt đối. Bám sát VIC/VHM/VRE để giao dịch F1.",
        "TÍN HIỆU GIẢ": "**TÍN HIỆU GIẢ — Bẫy nhiễu:** VIN 'mất kết nối' nhưng số liệu báo ảo. Dễ dính trap nếu nhìn VIN đánh F1.",
        "DECOUPLING": "**DECOUPLING — Rời bỏ:** VIN bị thị trường lãng quên. F1 đang chạy theo nhóm ngành khác.",
        "ANCHORING": "**ANCHORING — Neo giữ:** VIN đóng vai trò giữ nhịp, hãm phanh cho F1 nhưng không kéo giá.",
        "STATUS QUO": "**STATUS QUO — Quán tính:** Giữ nguyên chiến thuật cũ từ ngày t₀. Cấu trúc tương quan không thay đổi đáng kể.",
    }
    st.info(f"**Kết luận Kịch bản:** {regime_conclusion.get(dominant_regime, dominant_regime)}")

    c1, c2 = st.columns([1, 2])
    with c1:
        pie_data = counts.reset_index()
        pie_data.columns = ["Regime", "Count"]
        fig_pie = px.pie(pie_data, values="Count", names="Regime", hole=0.5, color="Regime", color_discrete_map=color_map)
        fig_pie.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)

    with c2:
        fig_scatter = px.scatter(
            re_df,
            x="Delta_PR_Corr",
            y="Delta_PR_Slope",
            color="Regime",
            color_discrete_map=color_map,
            hover_data=[re_df.index.date],
        )
        fig_scatter.add_hline(y=threshold, line_dash="dash", line_color="gray")
        fig_scatter.add_hline(y=-threshold, line_dash="dash", line_color="gray")
        fig_scatter.add_vline(x=threshold, line_dash="dash", line_color="gray")
        fig_scatter.add_vline(x=-threshold, line_dash="dash", line_color="gray")
        fig_scatter.update_layout(
            title_text="Ma trận Phân loại Kịch bản 2 chiều (ΔCorr vs ΔSlope)",
            height=350,
            template="plotly_white",
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    st.subheader("📈 Xu hướng Trạng thái theo Thời gian (Realtime Trend)")
    fig_trend = go.Figure()
    fig_trend.add_trace(
        go.Scatter(
            x=re_df.index,
            y=re_df["Delta_PR_Corr"],
            mode="lines",
            name="Δ Tương quan (Độ Bền vững)",
            line=dict(color="#e91e63", width=2),
        )
    )
    fig_trend.add_trace(
        go.Scatter(
            x=re_df.index,
            y=re_df["Delta_PR_Slope"],
            mode="lines",
            name="Δ Độ nhạy (Mức độ Tác động)",
            line=dict(color="#3f51b5", width=2),
        )
    )
    fig_trend.add_hline(y=threshold, line_dash="dash", line_color="gray", annotation_text="Ngưỡng Spike")
    fig_trend.add_hline(y=-threshold, line_dash="dash", line_color="gray", annotation_text="Ngưỡng Loosen")
    fig_trend.update_layout(
        height=400,
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    st.divider()
    st.header("📖 Hướng dẫn Đọc hiểu Kết quả")
    st.markdown(
        """
        Bảng dưới đây mô tả **5 kịch bản phân loại Regime** trong Event Study, được xác định dựa trên 
        sự thay đổi đồng thời của **Δ Tương quan (ΔCorr)** và **Δ Độ nhạy (ΔSlope)** so với ngày gốc t₀.
        """
    )

    guide_data = {
        "Kịch bản": ["🔗 COUPLING", "⚠️ TÍN HIỆU GIẢ", "🧊 DECOUPLING", "⚓ ANCHORING", "➖ STATUS QUO"],
        "Logic Toán học (ΔPR)": [
            "Corr ↑  |  Slope ↑",
            "Corr ↓  |  Slope ↑",
            "Corr ↓  |  Slope ↓",
            "Corr ↑  |  Slope ↓",
            "Nằm trong hộp Threshold",
        ],
        "Bản chất cơ khí (VIN vs. F1)": [
            "VIN và F1 dính chặt nhau + 1 lệnh VIN đẩy điểm F1 rất mạnh.",
            "F1 nhảy múa nhưng không theo hướng VIN + Slope báo ảo do VIN cạn Vol.",
            "Mỗi bên đi một nẻo + Lệnh VIN không làm F1 xê dịch đáng kể.",
            "VIN và F1 vẫn cùng hướng (đồng pha) + Nhưng tác động rất 'êm', không giật sốc.",
            "Tỷ lệ tác động của VIN lên F1 không thay đổi so với ngày gốc t₀.",
        ],
        "Trạng thái thực chiến": [
            "Siết chặt: VIN là hoa tiêu dẫn đường tuyệt đối.",
            "Bẫy nhiễu: VIN 'mất kết nối' nhưng số liệu báo ảo. Dễ dính trap nếu nhìn VIN đánh F1.",
            "Rời bỏ: VIN bị thị trường lãng quên. F1 đang chạy theo nhóm khác.",
            "Neo giữ: VIN đóng vai trò giữ nhịp, hãm phanh cho F1 nhưng không kéo giá.",
            "Quán tính: Giữ nguyên chiến thuật cũ từ ngày t₀.",
        ],
    }
    guide_df = pd.DataFrame(guide_data)
    st.dataframe(
        guide_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Kịch bản": st.column_config.TextColumn(width="medium"),
            "Logic Toán học (ΔPR)": st.column_config.TextColumn(width="medium"),
            "Bản chất cơ khí (VIN vs. F1)": st.column_config.TextColumn(width="large"),
            "Trạng thái thực chiến": st.column_config.TextColumn(width="large"),
        },
    )

    st.markdown(
        """
        **🗺️ Cách đọc Ma trận 2D (Scatter Plot):**
        - **Trục X (ΔCorr):** Thay đổi Tương quan so với t₀. Dương = tương quan tăng (VIN–F1 gắn chặt hơn). Âm = tương quan giảm (đang phân kỳ).
        - **Trục Y (ΔSlope):** Thay đổi Độ nhạy so với t₀. Dương = F1 phản ứng mạnh hơn per 1% VIN move. Âm = F1 phản ứng yếu hơn (đòn bẩy hạ xuống).
        - **4 góc phần tư** tương ứng với 4 kịch bản chủ động. Các điểm nằm trong hộp vuông trung tâm (trong ngưỡng Threshold) được phân loại là **STATUS QUO**.
        - **Đường đứt nét** trên biểu đồ là ranh giới Threshold — thay đổi thông số này trên thanh điều khiển trái để mở rộng/thu hẹp vùng STATUS QUO.
        """
    )
