# Fleet Dashboard with Three Views
# --------------------------------------------------------------
# Final version with outlier filtering and all chart code restored.

from __future__ import annotations
import re
import random
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Fleet Dashboard", layout="wide")
st.title("🚚 Fleet Performance Dashboard")

# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────
PLATE = re.compile(r"[A-Z]{2}\d{2}\s?[A-Z]{3}")
ALNUM = re.compile(r"[^A-Z0-9]")

def clean_key(val: Union[str, float, int, None]) -> Optional[str]:
    if pd.isna(val):
        return None
    s = str(val).upper()
    m = PLATE.search(s)
    return m.group(0).replace(" ", "") if m else ALNUM.sub("", s) or None

def clean_percentage(p):
    if pd.isna(p):
        return 0.0
    num = 0.0
    if isinstance(p, str):
        try:
            num = float(p.replace('%', '').strip())
        except (ValueError, TypeError):
            return 0.0
    elif isinstance(p, (int, float)):
        num = p
    return num / 100 if num > 1 else num

# ─────────────────────────────────────────────────────────────────────────────
# Load data & Correctly Process It
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    # Check if files exist
    for file in ["df2.xlsx", "df3.xlsx", "df4.xlsx"]:
        if not Path(file).exists():
            st.error(f"❌ File not found: {file}")
            st.stop()
    try:
        df2 = pd.read_excel("df2.xlsx", engine="openpyxl")
        tele_raw = pd.read_excel("df3.xlsx", engine="openpyxl")
        fuel_raw = pd.read_excel("df4.xlsx", engine="openpyxl")
    except Exception as e:
        st.error(f"Error reading Excel files: {e}")
        st.stop()

    # Step 1: Clean all column names FIRST.
    for df in [df2, tele_raw, fuel_raw]:
        df.columns = df.columns.str.strip().str.lower()

    # Step 2: Calculate 'idle_hours' from the 'idling time' column.
    idling_col_name = next((col for col in tele_raw.columns if "idling" in col and "time" in col), None)
    if idling_col_name:
        tele_raw['idle_hours'] = pd.to_timedelta(tele_raw[idling_col_name].astype(str), errors='coerce').dt.total_seconds() / 3600
    else:
        tele_raw['idle_hours'] = 0

    # Step 3: Handle merged cells in 'vehicle' column.
    if 'vehicle' in tele_raw.columns:
        tele_raw['vehicle'].ffill(inplace=True)

    # Step 4: Clean remaining string columns.
    for df in [df2, tele_raw, fuel_raw]:
        str_cols = df.select_dtypes("object").columns
        columns_to_exclude = ['idling (%)', 'idling time']
        str_cols = [col for col in str_cols if col not in columns_to_exclude]
        df[str_cols] = df[str_cols].apply(lambda c: c.str.strip() if hasattr(c, 'str') else c)
        
    return df2, tele_raw, fuel_raw

df2, tele_raw, fuel_raw = load_data()

# Get unique months for filtering
# Use a consolidated list of months from both telematics and fuel data
month_options = []
if "month" in tele_raw.columns:
    tele_raw['month_str_filter'] = tele_raw['month'].astype(str)
    month_options.extend(tele_raw['month_str_filter'].dropna().unique())

if 'date' in fuel_raw.columns:
    # Ensure date column is proper datetime
    fuel_raw['date'] = pd.to_datetime(fuel_raw['date'], errors='coerce')
    fuel_raw['month_str_filter'] = fuel_raw['date'].dt.strftime('%m/%Y')
    month_options.extend(fuel_raw['month_str_filter'].dropna().unique())

if not month_options:
    st.error("A 'month' or 'date' column is required for filtering.")
    st.stop()

# Get a unique, sorted list of months
month_options = sorted(list(set(month_options)))


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📅 Select Month")
    chosen_months = st.multiselect("Select month(s)", month_options, default=month_options)
    st.markdown("### 📊 Dashboard Info")
    st.info("""
    **View 1**: MPG & Cost Analysis
    - Fuel efficiency metrics
    - Cost per mile
    - Driver performance
    
    **View 2**: Idling Impact
    - Idle time costs
    - Environmental impact
    - Driver behavior patterns
        
    **View 3**: Idling Impact
    - Average Weekly Usage per Vehicle
    - Total Fleet Mileage per Week
    - Top 10 Vehicles by Average Weekly Usage
    """)

# ─────────────────────────────────────────────────────────────────────────────
# Create tabs for different views
# ─────────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "🚚 View 1: MPG & Cost-per-Mile", 
    "😴 View 2: Idling Impact Analysis",
    "📅 View 3: Weekly Usage Analysis"
])

# ─────────────────────────────────────────────────────────────────────────────
# VIEW 1: MPG & Cost-per-Mile
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.markdown("### 🏁 MPG & Pence-per-Mile League Table")
    if not chosen_months:
        st.warning("Please select at least one month from the sidebar.")
    else:
        def build_mpg_view(months: list[str]):
            tele = tele_raw[tele_raw["month_str_filter"].isin(months)].copy()
            
            tele["key"] = tele["vehicle"].apply(clean_key)
            tele["miles"] = pd.to_numeric(tele["distance"], errors="coerce")
            dist = (tele.dropna(subset=["key", "miles"])
                        .groupby("key", as_index=False)
                        .agg(total_miles=("miles", "sum")))
            
            fuel = fuel_raw.copy()
            fuel_filtered = fuel[fuel["month_str_filter"].isin(months)].copy()
            reg_col = "reg" if "reg" in fuel_filtered.columns else "reg."
            fuel_filtered["key"] = fuel_filtered[reg_col].apply(clean_key)
            fuel_filtered["litres"] = pd.to_numeric(fuel_filtered["quantity"], errors="coerce")
            fuel_filtered["fuel_cost"] = pd.to_numeric(fuel_filtered["net"], errors="coerce")
            fuel_agg = (fuel_filtered.dropna(subset=["key", "litres"])
                        .groupby("key", as_index=False)
                        .agg(litres=("litres", "sum"), fuel_cost=("fuel_cost", "sum")))
            
            merged = dist.merge(fuel_agg, on="key", how="inner")
            if merged.empty:
                return pd.DataFrame(), np.nan
                
            merged = merged[merged["total_miles"] > 0]
            merged["mpg"] = merged["total_miles"] / (merged["litres"] / 4.54609)
            merged["pence_per_mile"] = (merged["fuel_cost"] * 100) / merged["total_miles"]
            merged.replace([np.inf, -np.inf], np.nan, inplace=True)

            # Driver look-ups
            if 'vehicle reg' in df2.columns:
                df2["key"] = df2["vehicle reg"].apply(clean_key)
                
                # [THE FIX] De-duplicate the driver lookup to prevent replica rows
                # This keeps only the first driver entry found for each vehicle key.
                driver_lookup = df2[["key", "driver", "driver category"]].drop_duplicates(subset=['key'], keep='first')
                
                merged = merged.merge(driver_lookup, on="key", how="left")
            
            final = (merged.rename(columns={"key": "vehicle"})[
                ["vehicle", "driver", "driver category", "mpg", "pence_per_mile",
                 "total_miles", "litres", "fuel_cost"]]
                .round({"mpg": 1, "pence_per_mile": 1, "fuel_cost": 0}))
            
            miles_by_month = tele.groupby("month_str_filter")["miles"].sum()
            avg_miles_mon = miles_by_month.mean() if not miles_by_month.empty else np.nan
            return final, avg_miles_mon

        league_df, avg_miles = build_mpg_view(chosen_months)
        
        if not league_df.empty:
            st.dataframe(league_df.sort_values("mpg", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("No matching data found between fuel and telematics files for the selected period.")
        
        ppm_filtered = league_df[league_df['pence_per_mile'] < 100]
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Median MPG", f"{league_df['mpg'].median():.1f}" if not league_df.empty else "–")
        c2.metric("Fleet pence/mile", f"{ppm_filtered['pence_per_mile'].mean(skipna=True):.1f}p" if not ppm_filtered.empty else "–")
        c3.metric("Total fuel spend", f"£{league_df['fuel_cost'].sum():,.0f}")
        c4.metric("Avg miles / month", f"{avg_miles:,.0f}" if not pd.isna(avg_miles) else "–")

        st.markdown("---")
        st.markdown("### 💡 Recommendations")
        with st.container(border=True):
            st.markdown("""
            - **Investigate High-Cost Outliers:** Target vehicles with extremely high `pence_per_mile`. This often points to data quality issues where a large fuel purchase is recorded against a very short trip. Correcting the data logging process is the top priority for accurate reporting.

            - **Improve Driver Assignment:** Many trips are not linked to a specific driver. To enable driver performance analysis, ensure the driver lookup file (`df2.xlsx`) is complete and up-to-date for all vehicles.

            - **Identify Efficiency Champions:** Once data is clean, focus on the vehicles with the lowest `pence_per_mile`. The routes they take and the habits of their drivers can be used as a best-practice model for training the rest of the fleet.
            """)
# ─────────────────────────────────────────────────────────────────────────────
# VIEW 2: Idling Impact Analysis
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("### 😴 Fleet Idling Impact Analysis")
    
    if chosen_months:
        tele = tele_raw[tele_raw["month"].isin(chosen_months)].copy()
        
        if tele.empty:
            st.warning("No data found for the selected months.")
        else:
            tele["key"] = tele["vehicle"].apply(clean_key)
            tele["vehicle_name"] = tele["vehicle"]

            tele["idle_hours"] = tele["idle_hours"].fillna(0)

            if 'idling (%)' in tele.columns:
                tele['idling_%_decimal'] = tele['idling (%)'].apply(clean_percentage)
            else:
                tele['idling_%_decimal'] = 0

            tele['total_hours'] = tele['idle_hours'] / tele['idling_%_decimal'].replace(0, np.nan)
            tele['travel_hours'] = tele['total_hours'] - tele['idle_hours']
            tele['travel_hours'] = tele['travel_hours'].fillna(0).clip(lower=0)
            tele['total_hours'] = tele['total_hours'].fillna(tele['idle_hours'])
            
            vehicle_idle = tele.groupby(["key", "vehicle_name"]).agg(
                idle_hours=("idle_hours", "sum"),
                travel_hours=("travel_hours", "sum"),
                total_hours=("total_hours", "sum"),
                distance=("distance", "sum")
            ).reset_index()
            
            vehicle_idle["idling (%)"] = (vehicle_idle["idle_hours"] / vehicle_idle["total_hours"].replace(0, np.nan) * 100)
            
            if 'vehicle reg' in df2.columns:
                df2["key"] = df2["vehicle reg"].apply(clean_key)
                vehicle_idle = vehicle_idle.merge(df2[["key", "driver", "driver category"]], on="key", how="left")
            
            IDLE_FUEL_COST_PER_HOUR = 6
            vehicle_idle["idle_fuel_cost"] = vehicle_idle["idle_hours"] * IDLE_FUEL_COST_PER_HOUR
            
            CO2_PER_IDLE_HOUR = 2.4
            vehicle_idle["co2_emissions_kg"] = vehicle_idle["idle_hours"] * CO2_PER_IDLE_HOUR
            
            col1, col2, col3, col4 = st.columns(4)
            total_fleet_idle_hours = vehicle_idle["idle_hours"].sum()
            total_fleet_hours = vehicle_idle["total_hours"].sum()
            total_idle_cost = vehicle_idle["idle_fuel_cost"].sum()
            total_co2 = vehicle_idle["co2_emissions_kg"].sum()
            avg_idle_pct = (total_fleet_idle_hours / total_fleet_hours * 100) if total_fleet_hours > 0 else 0
            
            col1.metric("Total Fleet Idle Hours", f"{total_fleet_idle_hours:,.1f}")
            col2.metric("Total Idle Fuel Cost", f"£{total_idle_cost:,.0f}")
            col3.metric("Average Idle %", f"{avg_idle_pct:.1f}%")
            col4.metric("CO₂ Emissions (kg)", f"{total_co2:,.0f}")
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("##### Idle Percentage by Vehicle")
                fig_idle_pct = px.bar(
                    vehicle_idle.sort_values("idling (%)", ascending=True),
                    x="idling (%)", y="vehicle_name", color="idling (%)",
                    color_continuous_scale="Reds", text="idling (%)", hover_data=["driver", "idle_hours"])
                fig_idle_pct.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_idle_pct.add_vline(x=10, line_dash="dash", line_color="green", annotation_text="Target: 10%")
                fig_idle_pct.update_layout(height=400, yaxis_title=None)
                st.plotly_chart(fig_idle_pct, use_container_width=True)
            
            with col2:
                st.markdown("##### Idle Fuel Cost by Vehicle (£)")
                fig_cost = px.bar(
                    vehicle_idle.sort_values("idle_fuel_cost", ascending=True),
                    x="idle_fuel_cost", y="vehicle_name", color="idle_fuel_cost",
                    color_continuous_scale="Oranges", text="idle_fuel_cost", hover_data=["driver", "idle_hours"])
                fig_cost.update_traces(texttemplate='£%{text:,.0f}', textposition='outside')
                fig_cost.update_layout(height=400, yaxis_title=None)
                st.plotly_chart(fig_cost, use_container_width=True)
            
            st.markdown("### 📈 Monthly Idling Trends")
            
            # [FIX] Select a random sample of 5 vehicles for the trend chart if there are more than 5
            monthly_idle = tele.copy()
            monthly_idle["idling (%)"] = (monthly_idle["idle_hours"] / monthly_idle["total_hours"].replace(0, np.nan) * 100)
            monthly_idle_trend = monthly_idle.groupby(["month", "vehicle_name"])["idling (%)"].mean().reset_index()
            
            unique_vehicles = monthly_idle_trend['vehicle_name'].unique()
            if len(unique_vehicles) > 5:
                sampled_vehicles = random.sample(list(unique_vehicles), 5)
                trend_data_to_plot = monthly_idle_trend[monthly_idle_trend['vehicle_name'].isin(sampled_vehicles)]
            else:
                trend_data_to_plot = monthly_idle_trend

            fig_trend = px.line(
                trend_data_to_plot, x="month", y="idling (%)", color="vehicle_name",
                title="Idle Percentage Trend by Month (Sample of 5 Vehicles)", markers=True)
            fig_trend.add_hline(y=10, line_dash="dash", line_color="green", annotation_text="Target: 10%")
            fig_trend.update_layout(height=400)
            st.plotly_chart(fig_trend, use_container_width=True)
            
            st.markdown("### 📊 Detailed Idling Analysis")
            
            display_df = vehicle_idle.copy()
            if 'driver' not in display_df.columns: display_df['driver'] = 'N/A'
            if 'driver category' not in display_df.columns: display_df['driver category'] = 'N/A'

            display_df = display_df[[
                "vehicle_name", "driver", "driver category", "idling (%)", "idle_hours", "idle_fuel_cost", 
                "co2_emissions_kg", "distance"
            ]].rename(columns={
                "vehicle_name": "Vehicle", "driver": "Driver", "driver category": "Category",
                "idling (%)": "Idle %", "idle_hours": "Idle Hours", "idle_fuel_cost": "Idle Cost (£)",
                "co2_emissions_kg": "CO₂ (kg)", "distance": "Total Miles"
            }).round({
                "Idle %": 1, "Idle Hours": 1, "Idle Cost (£)": 0, "CO₂ (kg)": 0, "Total Miles": 0
            })
            
            st.dataframe(
                display_df.sort_values("Idle %", ascending=False),
                use_container_width=True, hide_index=True)
            
            st.markdown("### 💡 Key Insights & Recommendations")
            
            # [FIX] Restored full content to insights and recommendations
            high_idle = vehicle_idle[vehicle_idle["idling (%)"].fillna(0) > 15]
            if not high_idle.empty:
                st.warning(f"""
                **⚠️ High Idle Alert**: {len(high_idle)} vehicles exceed 15% idle time.
                - **Vehicles**: {', '.join(high_idle['vehicle_name'])}
                - Consider targeted driver training or setting idle-off timers.
                """)
            
            try:
                high_idle_for_calc = vehicle_idle[vehicle_idle["idling (%)"].fillna(0) > 10]
                if not high_idle_for_calc.empty:
                    mean_pct = high_idle_for_calc["idling (%)"].mean()
                    if mean_pct > 0:
                         total_excess_cost = high_idle_for_calc[high_idle_for_calc["idling (%)"] > 10]["idle_fuel_cost"].sum() * (1 - 10 / high_idle_for_calc["idling (%)"]).mean()
                    else:
                        total_excess_cost = 0
                else:
                    total_excess_cost = 0
            except (ZeroDivisionError, TypeError):
                total_excess_cost = 0

            st.success(f"""
            **💰 Cost Reduction Opportunity**:
            - If all vehicles over 10% idle were brought down to the 10% target, you could save an estimated **£{total_excess_cost:,.0f}** over the selected period.
            - The annual projected savings for this behavior change could be up to **£{total_excess_cost * (12 / len(chosen_months)) if chosen_months else 0:,.0f}**.
            """)
            
            st.info(f"""
            **🌍 Environmental Impact**:
            - Current period CO₂ from idling: **{total_co2:,.0f} kg**.
            - This is equivalent to the emissions from driving a standard diesel van for approximately **~{(total_co2 * 1.6 / 0.176):,.0f} miles**.
            - Offsetting this amount of CO₂ would require an estimated **~{total_co2 / 21:,.0f} trees** growing for one year.
            """)
            
    else:
        st.warning("Please select at least one month from the sidebar.")

# Footer
st.markdown("---")
if chosen_months:
    st.caption(f"📅 Showing data for: {', '.join(map(str, chosen_months))}")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW 3: Weekly Usage Analysis
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 📅 Fleet Weekly Usage Analysis")
    st.markdown("This analysis is based on the change in odometer `Mileage` between each fuel stop.")

    if not chosen_months:
        st.warning("Please select at least one month from the sidebar.")
    else:
        fuel_processed = fuel_raw.copy()
        
        fuel_processed['mileage'] = pd.to_numeric(fuel_processed['mileage'], errors='coerce')
        fuel_processed.dropna(subset=['date', 'mileage', 'reg.'], inplace=True)
        
        usage_df = fuel_processed[fuel_processed["month_str_filter"].isin(chosen_months)].copy()

        if usage_df.empty:
            st.warning("No fuel data found for the selected months.")
        else:
            usage_df.sort_values(by=['reg.', 'date'], inplace=True)
            usage_df['miles_driven'] = usage_df.groupby('reg.')['mileage'].diff()
            
            # [THE FIX] Add outlier filtering for realistic mileage
            # Filter out negative values and unrealistically high values (e.g., >3000 miles between stops)
            usage_df = usage_df[
                (usage_df['miles_driven'] > 0) & 
                (usage_df['miles_driven'] < 3000)
            ]
            
            if usage_df.empty:
                st.info("No valid usage data to display. This can happen if there is only one fuel stop per vehicle in the selected period.")
            else:
                usage_df['week_start'] = usage_df['date'].dt.to_period('W').apply(lambda r: r.start_time).dt.date
                
                weekly_vehicle_summary = usage_df.groupby(['reg.', 'week_start'])['miles_driven'].sum().reset_index()
                avg_weekly_usage = weekly_vehicle_summary['miles_driven'].mean()
                fleet_weekly_trend = weekly_vehicle_summary.groupby('week_start')['miles_driven'].sum().reset_index()
                vehicle_avg_weekly_usage = weekly_vehicle_summary.groupby('reg.')['miles_driven'].mean().reset_index()
                top_10_vehicles = vehicle_avg_weekly_usage.sort_values('miles_driven', ascending=False).head(10)
                
                st.metric("Average Weekly Usage per Vehicle", f"{avg_weekly_usage:,.0f} miles")
                
                st.markdown("---")
                st.markdown("##### Total Fleet Mileage per Week")
                
                # [THE FIX] Restored full chart code
                fig_trend = px.bar(
                    fleet_weekly_trend, x='week_start', y='miles_driven',
                    title='Total Fleet Mileage by Week',
                    labels={'week_start': 'Week', 'miles_driven': 'Total Miles Driven'}
                )
                fig_trend.update_layout(xaxis_title=None)
                st.plotly_chart(fig_trend, use_container_width=True)

                st.markdown("---")
                st.markdown("##### Top 10 Vehicles by Average Weekly Usage")
                
                # [THE FIX] Restored full chart code
                fig_top10 = px.bar(
                    top_10_vehicles.sort_values('miles_driven', ascending=True),
                    x='miles_driven', y='reg.', orientation='h',
                    title='Top 10 Vehicles by Average Weekly Usage', text='miles_driven',
                    labels={'reg.': 'Vehicle', 'miles_driven': 'Average Miles per Week'}
                )
                fig_top10.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                fig_top10.update_layout(yaxis_title=None)
                st.plotly_chart(fig_top10, use_container_width=True)