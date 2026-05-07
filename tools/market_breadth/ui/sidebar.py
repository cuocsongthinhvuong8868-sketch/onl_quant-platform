from datetime import timedelta
import pandas as pd
import streamlit as st


def render_sidebar(df_breadth: pd.DataFrame):
    st.sidebar.header("History Measurement")

    min_date = df_breadth.index.min().date()
    max_date = df_breadth.index.max().date()

    default_start = max(min_date, max_date - timedelta(days=365))
    start_date = st.sidebar.date_input("Từ ngày", value=default_start, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("Đến ngày", value=max_date, min_value=min_date, max_value=max_date)

    if start_date > end_date:
        st.sidebar.error("'Từ ngày' phải trước hoặc bằng 'Đến ngày'.")

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    return start_date, end_date, start_dt, end_dt
