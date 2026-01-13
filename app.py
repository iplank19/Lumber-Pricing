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
existing_profiles = [f.replace(".json", "") for f in os.listdir(".") if f.endswith(".json")]
if not existing_profiles:
    existing_profiles = ["Default"]

st.sidebar.header("📁 Profile Manager")
selected_profile = st.sidebar.selectbox("Active Profile", existing_profiles)
new_profile_name = st.sidebar.text_input("Create New Profile (Type name and hit Enter)")

# Logic: If they typed a new name, use it. Otherwise use the dropdown.
current_profile = new_profile_name if new_profile_name else selected_profile

def load_config(profile):
    filename = f"{profile}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return None # This is the trigger for the blank template

# Try to load. If the file doesn't exist, 'saved_data' becomes an empty dictionary.
saved_data = load_config(current_profile) or {}

st.title(f"🌲 Pricing Portal: {current_profile}")

# --- SIDEBAR: SETTINGS (Reset if profile is new) ---
st.sidebar.markdown("---")
st.sidebar.header("1. Contact Settings")
gmail_user = st.sidebar.text_input("Your Gmail", value=saved_data.get("gmail_user", ""))
app_password = st.sidebar.text_input("App Password", type="password", value=saved_data.get("app_pass", ""))
work_email = st.sidebar.text_input("Work Email", value=saved_data.get("work_email", ""))

st.sidebar.markdown("---")
st.sidebar.header("2. State/Prov Rates")
states_input, rates_input = [], []
# If profile is new, these return empty strings and 0.0 rates
d_states = saved_data.get("states", ["AL", "AR", "MS", "FL", "GA", "TX"])
d_rates = saved_data.get("rates", [0.00] * 6) 

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    # The key= must be unique per profile to force a refresh
    s = col_s.text_input(f"St/Pr {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = dict(zip(states_input, rates_input))

# --- DATA TABLES ---
types = ["2x4 #1", "2x4 #2", "2x6 #1"]
lengths = ["8'", "10'", "12'", "14'", "16'", "18'", "20'"]
master_products = [f"{t.split(' ')[0]} {l} {t.split(' ')[1]}" for t in types for l in lengths]

# MASTER TABLE: Keeps the template names but wipes prices and origins
saved_master = saved_data.get("master_table_data")
df_master = st.data_editor(
    pd.DataFrame(saved_master) if saved_master else pd.DataFrame({
        "Product": master_products, 
        "FOB Price": 0.0, 
        "Origin": "", 
        "Availability": "1-2 TL", 
        "Ship Time": "Prompt"
    }), 
    key=f"m_tab_{current_profile}", 
    use_container_width=True
)

# SPECIALTY TABLE: Wipes everything—names, prices, origins
saved_spec = saved_data.get("spec_table_data")
df_spec = st.data_editor(
    pd.DataFrame(saved_spec) if saved_spec else pd.DataFrame({
        "Product": [""] * 10, 
        "FOB Price": [0.0] * 10, 
        "Origin": [""] * 10, 
        "Availability": ["1-2 TL"] * 10, 
        "Ship Time": ["Prompt"] * 10
    }), 
    num_rows="dynamic", 
    key=f"s_tab_{current_profile}", 
    use_container_width=True
)

# --- SAVE LOGIC ---
if st.sidebar.button("💾 SAVE PROFILE", use_container_width=True):
    config_to_save = {
        "gmail_user": gmail_user, "app_pass": app_password, "work_email": work_email,
        "states": states_input, "rates": rates_input, 
        "master_table_data": df_master.to_dict('records'),
        "spec_table_data": df_spec.to_dict('records')
    }
    filename = f"{current_profile}.json"
    with open(filename, "w") as f:
        json.dump(config_to_save, f)
    st.sidebar.success(f"Profile '{current_profile}' saved!")
    time.sleep(1)
    st.rerun()

# --- CALCULATION ENGINE (REMAINS THE SAME) ---
# [Your North American run_report and get_miles logic here]