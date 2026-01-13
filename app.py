import streamlit as st
import pandas as pd
import requests
import math
import json
import os
import smtplib
import time
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- APP UI SETUP ---
st.set_page_config(page_title="Lumber Pricing Portal", layout="wide")

# --- PROFILE & CONFIG LOGIC ---
# Get list of existing profiles
existing_profiles = [f.replace(".json", "") for f in os.listdir(".") if f.endswith(".json")]
if not existing_profiles:
    existing_profiles = ["Default"]

st.sidebar.header("📁 Profile Manager")
selected_profile = st.sidebar.selectbox("Active Profile", existing_profiles)
new_profile_name = st.sidebar.text_input("Create New Profile (Type name here)")

# This determines which profile we are actually trying to look at
current_profile = new_profile_name if new_profile_name else selected_profile

def load_config(profile):
    filename = f"{profile}.json"
    # ONLY load if the file actually exists. Otherwise, return None to trigger blanks.
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return None 

# Try to load. If it returns None, 'saved_data' will be an empty dictionary.
saved_data = load_config(current_profile) or {}

st.title(f"🌲 Pricing Portal: {current_profile}")

# --- SIDEBAR: SETTINGS ---
st.sidebar.markdown("---")
st.sidebar.header("1. Contact Settings")
gmail_user = st.sidebar.text_input("Your Gmail", value=saved_data.get("gmail_user", ""))
app_password = st.sidebar.text_input("App Password", type="password", value=saved_data.get("app_pass", ""))
work_email = st.sidebar.text_input("Work Email", value=saved_data.get("work_email", ""))

st.sidebar.markdown("---")
st.sidebar.header("2. State/Prov Rates")
states_input, rates_input = [], []
# Default values for a brand new profile
d_states = saved_data.get("states", ["AL", "AR", "MS", "FL", "GA", "TX"])
d_rates = saved_data.get("rates", [0.00, 0.00, 0.00, 0.00, 0.00, 0.00]) # Set to 0 for new profiles

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St/Pr {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = dict(zip(states_input, rates_input))

st.sidebar.markdown("---")
st.sidebar.header("3. Logistics")
sh_threshold = st.sidebar.number_input("Short Haul Limit", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Std Divisor", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR Divisor", value=saved_data.get("msr_div", 25.0))

# --- DATA TABLES ---
types = ["2x4 #1", "2x4 #2", "2x6 #1"]
lengths = ["8'", "10'", "12'", "14'", "16'", "18'", "20'"]
master_products = [f"{t.split(' ')[0]} {l} {t.split(' ')[1]}" for t in types for l in lengths]

# MASTER TABLE: Loads data if profile exists, otherwise $0.00 prices
saved_master = saved_data.get("master_table_data")
df_master = st.data_editor(
    pd.DataFrame(saved_master) if saved_master else pd.DataFrame({
        "Product": master_products, "FOB Price": 0.0, "Origin": "", "Availability": "1-2 TL", "Ship Time": "Prompt"
    }), 
    key=f"m_tab_{current_profile}", 
    use_container_width=True
)

# SPECIALTY TABLE: Loads data if profile exists, otherwise completely blank rows
saved_spec = saved_data.get("spec_table_data")
df_spec = st.data_editor(
    pd.DataFrame(saved_spec) if saved_spec else pd.DataFrame({
        "Product": [""]*5, "FOB Price": [0.0]*5, "Origin": ["" ]*5, "Availability": ["1-2 TL"]*5, "Ship Time": ["Prompt"]*5
    }), 
    num_rows="dynamic", 
    key=f"s_tab_{current_profile}", 
    use_container_width=True
)

# --- SAVE LOGIC ---
if st.sidebar.button("💾 SAVE & CREATE PROFILE", use_container_width=True):
    config_to_save = {
        "gmail_user": gmail_user, "app_pass": app_password, "work_email": work_email,
        "states": states_input, "rates": rates_input, "sh_threshold": sh_threshold,
        "sh_floor": sh_floor, "uni_div": uni_div, "msr_div": msr_div,
        "master_table_data": df_master.to_dict('records'),
        "spec_table_data": df_spec.to_dict('records')
    }
    filename = f"{current_profile}.json"
    with open(filename, "w") as f:
        json.dump(config_to_save, f)
    st.sidebar.success(f"Profile '{current_profile}' Created/Updated!")
    time.sleep(1)
    st.rerun()

# --- ENGINE & OUTPUT ---
# (Same North American engine as before)
@st.cache_data
def get_miles(origin, destination):
    if not origin or not destination: return None
    time.sleep(1.2)
    try:
        headers = {'User-Agent': 'lumber_v13_rollout'}
        url_a = f"https://nominatim.openstreetmap.org/search?q={origin}&format=json&limit=1"
        url_b = f"https://nominatim.openstreetmap.org/search?q={destination}&format=json&limit=1"
        res_a = requests.get(url_a, headers=headers).json()
        res_b = requests.get(url_b, headers=headers).json()
        if not res_a or not res_b: return None
        c_a = (res_a[0]['lon'], res_a[0]['lat']); c_b = (res_b[0]['lon'], res_b[0]['lat'])
        r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
        return requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
    except: return None

def run_report(cities, spec_only):
    out = ""
    combined = df_spec if spec_only else pd.concat([df_master, df_spec])
    # ... (rest of report logic) ...
    return out

# [Keep your existing report generation and email buttons at the bottom]