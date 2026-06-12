import plotly.express as px
import streamlit as st


def render_table(df_result):
    fmt = {
        "Geomean ROE": "{:.2%}",
        "Stdev ROE": "{:.2%}",
        "Cash Payout Ratio": "{:.2%}",
        "Cash Dividends Paid 20Q": "{:,.0f}",
        "Net Profit 20Q": "{:,.0f}",
        "BVPS": "{:,.0f}",
        "Daily Close": "{:.2f}",
        "P/B Gốc": "{:.2f}",
        "P/B Statistics": "{:.2f}",
        "P/B Kịch Bản": "{:.2f}",
        "ROE Retention": "{:.2%}",
        "Risk Penalty": "{:.2%}",
        "Disciplined Return": "{:.2%}",
        "Economic Alpha": "{:.2%}",
    }
    st.dataframe(
        df_result.style.format(fmt, na_rep="—").background_gradient(
            subset=["Economic Alpha"], cmap="RdYlGn"
        )
    )


def render_alpha_chart(df_result):
    ticker_col = "Ticker" if "Ticker" in df_result.columns else "Ngân hàng"
    chart = df_result[[ticker_col, "Economic Alpha"]].copy()
    chart["Economic Alpha"] = chart["Economic Alpha"] * 100.0

    fig = px.bar(
        chart,
        x=ticker_col,
        y="Economic Alpha",
        color="Economic Alpha",
        color_continuous_scale="RdYlGn",
        labels={"Economic Alpha": "Economic Alpha (%)"},
        title="Economic Alpha (%) theo ngân hàng",
    )
    fig.update_traces(texttemplate="%{y:.2f}%", textposition="outside")
    fig.update_layout(xaxis_tickangle=-45, title_x=0.5)
    st.plotly_chart(fig, use_container_width=True)
