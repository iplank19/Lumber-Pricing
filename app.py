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

# --- PERSISTENT STORAGE LOGIC ---
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config_dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_dict, f)

saved_data = load_config()

# --- APP UI SETUP ---
st.set_page_config(page_title="Lumber Pricing Portal", layout="wide")
st.title("Lumber Pricing Portal")

# --- SIDEBAR: SETTINGS & CONFIG ---
st.sidebar.header("1. Email & Contact")
gmail_user = st.sidebar.text_input("Your Gmail", value=saved_data.get("gmail_user", ""))
app_password = st.sidebar.text_input("Gmail App Password", type="password", value=saved_data.get("app_pass", ""))
work_email = st.sidebar.text_input("Work Email", value=saved_data.get("work_email", ""))

st.sidebar.markdown("---")
st.sidebar.header("2. State Rate Matrix")
states_input, rates_input = [], []
d_states = saved_data.get("states", ["AL", "AR", "MS", "FL", "GA", "TX"])
d_rates = saved_data.get("rates", [3.50, 4.25, 3.75, 4.00, 2.00, 3.80])

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}").upper()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 3.50, key=f"r{i}")
    states_input.append(s); rates_input.append(r)
rate_map = dict(zip(states_input, rates_input))

st.sidebar.markdown("---")
st.sidebar.header("3. Freight & Divisors")
sh_threshold = st.sidebar.number_input("Short Haul Limit (Miles)", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor ($)", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Standard Divisor (MBF)", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR Divisor (MBF)", value=saved_data.get("msr_div", 25.0))

st.sidebar.markdown("---")
st.sidebar.header("4. Destinations")
standard_cities = saved_data.get("standard_cities", ["Chicago, IL", "Houston, TX", "Atlanta, GA"])
selected_preset = st.sidebar.selectbox("Select City", standard_cities + ["Custom...", "Edit List"])

if selected_preset == "Edit List":
    new_list = st.sidebar.text_area("One city per line", value="\n".join(standard_cities))
    standard_cities = [c.strip() for c in new_list.split("\n") if c.strip()]
    dest_city = "Chicago, IL"
else:
    dest_city = st.sidebar.text_input("City Name", value="Chicago, IL") if selected_preset == "Custom..." else selected_preset

# --- DATA TABLES ---
types = ["2x4 #1", "2x4 #2", "2x6 #1"]
lengths = ["8'", "10'", "12'", "14'", "16'", "18'", "20'"]
master_products = [f"{t.split(' ')[0]} {l} {t.split(' ')[1]}" for t in types for l in lengths]

saved_master = saved_data.get("master_table_data")
df_master = st.data_editor(pd.DataFrame(saved_master) if saved_master else pd.DataFrame({
    "Product": master_products, "FOB Price": 0.0, "Origin": "Warrenton, GA", "Availability": "1-2 TL", "Ship Time": "Prompt"
}), key="m_v23", use_container_width=True)

saved_spec = saved_data.get("spec_table_data")
df_spec = st.data_editor(pd.DataFrame(saved_spec) if saved_spec else pd.DataFrame({
    "Product": "", "FOB Price": 0.0, "Origin": "Warren, AR", "Availability": "1-2 TL", "Ship Time": "Prompt"
}), num_rows="dynamic", key="s_v23", use_container_width=True)

# --- SAVE BUTTON ---
if st.sidebar.button("💾 SAVE CONFIG & TEMPLATE"):
    config_to_save = {
        "gmail_user": gmail_user, "app_pass": app_password, "work_email": work_email,
        "states": states_input, "rates": rates_input, "sh_threshold": sh_threshold,
        "sh_floor": sh_floor, "uni_div": uni_div, "msr_div": msr_div,
        "standard_cities": standard_cities,
        "master_table_data": df_master.to_dict('records'),
        "spec_table_data": df_spec.to_dict('records')
    }
    save_config(config_to_save)
    st.sidebar.success("All settings and prices saved!")

# --- CALCULATION ENGINE ---
@st.cache_data
def get_miles(origin, destination):
    time.sleep(1.2) # Prevent map service throttling
    try:
        headers = {'User-Agent': 'lumber_pricing_app_v10'}
        url_a = f"https://nominatim.openstreetmap.org/search?q={origin}, USA&format=json&limit=1"
        url_b = f"https://nominatim.openstreetmap.org/search?q={destination}, USA&format=json&limit=1"
        res_a = requests.get(url_a, headers=headers).json()
        res_b = requests.get(url_b, headers=headers).json()
        if not res_a or not res_b: return None
        c_a = (res_a[0]['lon'], res_a[0]['lat'])
        c_b = (res_b[0]['lon'], res_b[0]['lat'])
        r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
        return requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
    except: return None

def run_report(cities, spec_only):
    out = ""
    combined = df_spec if spec_only else pd.concat([df_master, df_spec])
    for city in cities:
        rows = []
        for _, r in combined.iterrows():
            if r['FOB Price'] > 0 and str(r['Product']).strip():
                rate = next((v for k, v in rate_map.items() if k and k in str(r['Origin']).upper()), 0.0)
                miles = get_miles(r['Origin'], city)
                if miles:
                    cost = sh_floor if miles < sh_threshold else miles * rate
                    div = msr_div if "MSR" in str(r['Product']).upper() else uni_div
                    p = math.ceil(r['FOB Price'] + (cost / div))
                    rows.append(f"{r['Product']:<25} {r['Availability']:<10} {r['Ship Time']:<10} ${p}")
                else: st.warning(f"Could not calculate distance for {r['Origin']} to {city}")
        if rows:
            out += f"LUMBER QUOTE - {city.upper()}\n{'PRODUCT':<25} {'AVAIL':<10} {'SHIP':<10} {'PRICE'}\n"
            out += "-"*55 + "\n" + "\n".join(rows) + "\n\n" + "="*55 + "\n\n"
    return out

# --- OUTPUT SECTION ---
st.markdown("---")
s_only = st.toggle("Specialty Items ONLY")
col_g1, col_g2 = st.columns(2)
with col_g1:
    if st.button("Generate Single Quote", type="primary", use_container_width=True):
        st.session_state.txt = run_report([dest_city], s_only)
with col_g2:
    if st.button("⚡ BULK GENERATE ALL CITIES", use_container_width=True):
        st.session_state.txt = run_report(standard_cities, s_only)

if 'txt' in st.session_state and st.session_state.txt:
    st.text_area("Report Output", value=st.session_state.txt, height=400)
    
    c_email1, c_email2 = st.columns(2)
    with c_email1:
        if st.button("📧 Direct Blast (Gmail)", use_container_width=True):
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                    srv.login(gmail_user, app_password)
                    msg = MIMEMultipart()
                    msg['From'], msg['To'], msg['Subject'] = gmail_user, work_email, f"Price Run - {dest_city}"
                    msg.attach(MIMEText(st.session_state.txt, 'plain'))
                    srv.sendmail(gmail_user, work_email, msg.as_string())
                    st.success("Sent via Gmail!")
            except Exception as e:
                st.error(f"Firewall Blocked Gmail: {e}")
                
    with c_email2:
        # Outlook Mailto Generator
        subject_enc = urllib.parse.quote(f"Lumber Quote - {dest_city}")
        body_enc = urllib.parse.quote(st.session_state.txt)
        mailto_link = f"mailto:{work_email}?subject={subject_enc}&body={body_enc}"
        st.markdown(f'<a href="{mailto_link}" target="_blank" style="text-decoration:none;"><div style="background-color:#0078d4;color:white;padding:10px;text-align:center;border-radius:5px;font-weight:bold;">📬 Draft in Outlook (Firewall Safe)</div></a>', unsafe_allow_html=True)