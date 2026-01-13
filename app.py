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
selected_profile = st.sidebar.selectbox("Select Existing Profile", existing_profiles)
new_profile_name = st.sidebar.text_input("OR Create New Profile (Type & Hit Enter)")

current_profile = new_profile_name if new_profile_name else selected_profile

def load_config(profile):
    filename = f"{profile}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return None 

saved_data = load_config(current_profile) or {}

st.title(f"🌲 Pricing Portal: {current_profile}")

# --- SIDEBAR: CONTACTS ---
st.sidebar.markdown("---")
st.sidebar.header("1. Contact Settings")
gmail_user = st.sidebar.text_input("Your Gmail", value=saved_data.get("gmail_user", ""))
app_password = st.sidebar.text_input("App Password", type="password", value=saved_data.get("app_pass", ""))
work_email = st.sidebar.text_input("Work Email", value=saved_data.get("work_email", ""))

# --- SIDEBAR: STATE RATES ---
st.sidebar.markdown("---")
st.sidebar.header("2. State/Prov Rates")
states_input, rates_input = [], []
d_states = saved_data.get("states", ["", "", "", "", "", ""]) 
d_rates = saved_data.get("rates", [0.00] * 6) 

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St/Pr {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = dict(zip(states_input, rates_input))

# --- SIDEBAR: LOGISTICS (Board Footage Divisors) ---
st.sidebar.markdown("---")
st.sidebar.header("3. Logistics & Divisors")
sh_threshold = st.sidebar.number_input("Short Haul Limit (Miles)", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor ($)", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Std MBF per Truck", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR MBF per Truck", value=saved_data.get("msr_div", 25.0))

# --- SIDEBAR: DESTINATIONS ---
st.sidebar.markdown("---")
st.sidebar.header("4. Destinations")
default_cities = ["Chicago, IL", "Houston, TX", "Atlanta, GA", "Toronto, ON"]
city_list = saved_data.get("standard_cities", default_cities)

selected_city_preset = st.sidebar.selectbox("Choose Destination", city_list + ["Custom...", "Edit List"])

if selected_city_preset == "Edit List":
    new_city_list = st.sidebar.text_area("One city per line", value="\n".join(city_list))
    city_list = [c.strip() for c in new_city_list.split("\n") if c.strip()]
    dest_city = city_list[0] if city_list else "Chicago, IL"
elif selected_city_preset == "Custom...":
    dest_city = st.sidebar.text_input("Enter City, ST", value="Chicago, IL")
else:
    dest_city = selected_city_preset

# --- DATA TABLES ---
st.subheader("1. Standard Offerings")
saved_master = saved_data.get("master_table_data")
df_master = st.data_editor(
    pd.DataFrame(saved_master) if saved_master else pd.DataFrame({
        "Product": [""] * 15, "FOB Price": [0.0] * 15, "Origin": [""] * 15, "Availability": ["Prompt"] * 15, "Ship Time": ["Prompt"] * 15
    }), 
    key=f"m_tab_{current_profile}", use_container_width=True
)

st.subheader("2. Specialty Items")
saved_spec = saved_data.get("spec_table_data")
df_spec = st.data_editor(
    pd.DataFrame(saved_spec) if saved_spec else pd.DataFrame({
        "Product": [""] * 10, "FOB Price": [0.0] * 10, "Origin": [""] * 10, "Availability": ["Prompt"] * 10, "Ship Time": ["Prompt"] * 10
    }), 
    num_rows="dynamic", key=f"s_tab_{current_profile}", use_container_width=True
)

# --- SAVE LOGIC ---
if st.sidebar.button("💾 SAVE PROFILE", use_container_width=True):
    config_to_save = {
        "gmail_user": gmail_user, "app_pass": app_password, "work_email": work_email,
        "states": states_input, "rates": rates_input, 
        "sh_threshold": sh_threshold, "sh_floor": sh_floor,
        "uni_div": uni_div, "msr_div": msr_div,
        "standard_cities": city_list,
        "master_table_data": df_master.to_dict('records'),
        "spec_table_data": df_spec.to_dict('records')
    }
    with open(f"{current_profile}.json", "w") as f:
        json.dump(config_to_save, f)
    st.sidebar.success(f"Profile '{current_profile}' saved!")
    time.sleep(1)
    st.rerun()

# --- ENGINE ---
@st.cache_data
def get_miles(origin, destination):
    if not origin or not destination: return None
    time.sleep(1.2)
    try:
        headers = {'User-Agent': 'lumber_v17'}
        url_a = f"https://nominatim.openstreetmap.org/search?q={origin}&format=json&limit=1"
        url_b = f"https://nominatim.openstreetmap.org/search?q={destination}&format=json&limit=1"
        res_a = requests.get(url_a, headers=headers).json()
        res_b = requests.get(url_b, headers=headers).json()
        c_a = (res_a[0]['lon'], res_a[0]['lat']); c_b = (res_b[0]['lon'], res_b[0]['lat'])
        r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
        return requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
    except: return None

def run_report(cities, spec_only):
    out = ""
    combined = df_spec if spec_only else pd.concat([df_master, df_spec])
    for city in cities:
        rows = []
        for _, r in combined.iterrows():
            if float(r['FOB Price']) > 0 and str(r['Product']).strip():
                rate = next((v for k, v in rate_map.items() if k and k in str(r['Origin']).upper()), 0.0)
                miles = get_miles(r['Origin'], city)
                if miles:
                    # Uses the divisors from the sidebar!
                    cost = sh_floor if miles < sh_threshold else miles * rate
                    div = msr_div if "MSR" in str(r['Product']).upper() else uni_div
                    p = math.ceil(r['FOB Price'] + (cost / div))
                    rows.append(f"{r['Product']:<25} {r['Availability']:<10} {r['Ship Time']:<10} ${p}")
        if rows:
            out += f"LUMBER QUOTE - {city.upper()}\n{'PRODUCT':<25} {'AVAIL':<10} {'SHIP':<10} {'PRICE'}\n" + "-"*55 + "\n" + "\n".join(rows) + "\n\n"
    return out

# --- OUTPUT ---
st.markdown("---")
s_only = st.toggle("Specialty Items ONLY")
if st.button(f"Generate Quote for {dest_city}", type="primary"):
    st.session_state.txt = run_report([dest_city], s_only)

if st.button("⚡ BULK ALL CITIES"):
    st.session_state.txt = run_report(city_list, s_only)

if 'txt' in st.session_state:
    st.text_area("Report Output", value=st.session_state.txt, height=300)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📧 Direct Blast (Gmail)", use_container_width=True):
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                    srv.login(gmail_user, app_password)
                    msg = MIMEMultipart()
                    msg['From'], msg['To'], msg['Subject'] = gmail_user, work_email, f"Lumber Quote"
                    msg.attach(MIMEText(st.session_state.txt, 'plain'))
                    srv.sendmail(gmail_user, work_email, msg.as_string())
                    st.success("Sent!")
            except: st.error("Firewall blocked. Use Outlook.")
    with c2:
        sub_enc = urllib.parse.quote(f"Lumber Quote")
        body_enc = urllib.parse.quote(st.session_state.txt)
        mailto_link = f"mailto:{work_email}?subject={sub_enc}&body={body_enc}"
        st.markdown(f'<a href="{mailto_link}" target="_blank" style="text-decoration:none;"><div style="background-color:#0078d4;color:white;padding:10px;text-align:center;border-radius:5px;font-weight:bold;">📬 Draft in Outlook</div></a>', unsafe_allow_html=True)