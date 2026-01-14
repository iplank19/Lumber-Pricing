import streamlit as st
import pandas as pd
import requests
import math
import json
import os
import time
import io
import zipfile
import urllib.parse

# --- APP UI SETUP ---
st.set_page_config(page_title="Lumber Hub: Total Multi-Profile", layout="wide")

# --- PROFILE & DYNAMIC FILE PATHS ---
# Scan for profiles but exclude auxiliary data files
existing_profiles = [f.replace(".json", "") for f in os.listdir(".") if f.endswith(".json") 
                     and "_matrices" not in f and "_mileage" not in f]
if not existing_profiles: existing_profiles = ["Default"]

st.sidebar.header("📁 Profile Manager")
selected_profile = st.sidebar.selectbox("Select Active Profile", existing_profiles)
new_profile_name = st.sidebar.text_input("OR Create New (Blank Slate)")
current_profile = new_profile_name if new_profile_name else selected_profile

# Dynamic File Paths based on Profile Name
CONFIG_FILE = f"{current_profile}.json"
CUSTOMER_DB_FILE = f"{current_profile}_customers.csv"
MATRIX_FILE = f"{current_profile}_matrices.json"
MILEAGE_CACHE_FILE = f"{current_profile}_mileage.json"

# --- CORE DATA LOGIC ---
def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            try: return json.load(f)
            except: return {}
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f)

# Initialize Session Cache - Reset if profile changes
if 'm_cache' not in st.session_state or st.session_state.get('active_profile') != current_profile:
    st.session_state.m_cache = load_json(MILEAGE_CACHE_FILE)
    st.session_state.active_profile = current_profile

saved_data = load_json(CONFIG_FILE)

# --- SIDEBAR: 1. PRICING RATES ---
st.sidebar.markdown("---")
st.sidebar.header("1. Pricing Rates")
states_input, rates_input = [], []
# Defaults for a brand new profile
d_states = saved_data.get("states", ["", "", "", "", "", ""]) 
d_rates = saved_data.get("rates", [0.00] * 6) 

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper().strip()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = {k: v for k, v in zip(states_input, rates_input) if k}

sh_threshold = st.sidebar.number_input("Short Haul Limit", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor ($)", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Std Divisor", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR Divisor", value=saved_data.get("msr_div", 25.0))
round_val = st.sidebar.selectbox("Rounding", options=[1, 5, 10, 0], index=1)

# --- SIDEBAR: 2. MASTER CITIES ---
st.sidebar.markdown("---")
st.sidebar.header("2. Destination Cities")
saved_cities = saved_data.get("cities_list", "")
cities_input = st.sidebar.text_area("Master City List", value=saved_cities, height=150)
active_cities = [c.strip() for c in cities_input.split("\n") if c.strip()]
dest_city = st.sidebar.selectbox("Target for Single Quote", active_cities) if active_cities else "None"

# --- SIDEBAR: 3. EXPORT CENTER ---
st.sidebar.markdown("---")
st.sidebar.header("📥 Backup Profile")
def create_backup_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Include only files relevant to the CURRENT profile
        files_to_back = [CONFIG_FILE, CUSTOMER_DB_FILE, MATRIX_FILE, MILEAGE_CACHE_FILE]
        for f in files_to_back:
            if os.path.exists(f): zf.write(f)
    return buf.getvalue()

st.sidebar.download_button(f"📦 DOWNLOAD {current_profile.upper()} BACKUP", data=create_backup_zip(), file_name=f"{current_profile}_backup.zip", mime="application/zip", use_container_width=True)

# --- CALCULATION ENGINE ---
def get_miles(origin, destination):
    if not origin or not destination: return None
    lane_key = f"{origin.strip().upper()} to {destination.strip().upper()}"
    if lane_key in st.session_state.m_cache: return st.session_state.m_cache[lane_key]
    time.sleep(1.2)
    try:
        headers = {'User-Agent': 'lumber_hub_v100'}
        res_a = requests.get(f"https://nominatim.openstreetmap.org/search?q={origin.strip()}&format=json&limit=1", headers=headers).json()
        res_b = requests.get(f"https://nominatim.openstreetmap.org/search?q={destination.strip()}&format=json&limit=1", headers=headers).json()
        c_a = (res_a[0]['lon'], res_a[0]['lat']); c_b = (res_b[0]['lon'], res_b[0]['lat'])
        r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
        miles = requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
        st.session_state.m_cache[lane_key] = miles
        save_json(MILEAGE_CACHE_FILE, st.session_state.m_cache)
        return miles
    except: return None

def run_calculation(city, df_m, df_s, r_map, r_rule, inc_m, inc_s):
    combined_list = []
    if inc_m: combined_list.append(df_m)
    if inc_s: combined_list.append(df_s)
    if not combined_list: return None
    combined = pd.concat(combined_list)
    combined = combined[pd.to_numeric(combined['FOB Price'], errors='coerce') > 0]
    rows = []
    for _, r in combined.iterrows():
        prod, origin = str(r.get('Product', '')), str(r.get('Origin', '')).upper()
        avail, ship = str(r.get('Availability', 'Prompt')), str(r.get('Ship Time', 'Prompt'))
        if not prod or not origin: continue
        rate = next((v for k, v in r_map.items() if k in origin), None)
        if rate is None: continue
        miles = get_miles(origin, city)
        if miles:
            cost = sh_floor if miles < sh_threshold else miles * rate
            div = msr_div if "MSR" in prod.upper() else uni_div
            raw_p = float(r['FOB Price']) + (cost / div)
            p = math.ceil(raw_p / r_rule) * r_rule if r_rule > 0 else round(raw_p, 2)
            rows.append(f"{prod[:28]:<28} {avail[:10]:<10} {ship[:10]:<10} ${p:>7}")
    if rows:
        header = f"{'PRODUCT':<28} {'AVAIL':<10} {'SHIP':<10} {'PRICE':>8}"
        return f"QUOTE: {city.upper()}\n{header}\n{'-'*60}\n" + "\n".join(rows)
    return None

# --- NAVIGATION ---
tab_pricing, tab_customers = st.tabs(["🌲 Pricing Engine", "👥 CRM & Auto-Draft"])

# --- TAB 1: PRICING ENGINE ---
with tab_pricing:
    st.header(f"Profile Workspace: {current_profile}")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Standard Offerings")
        m_data = saved_data.get("master_table_data")
        df_master = st.data_editor(pd.DataFrame(m_data) if m_data else pd.DataFrame({"Product": [""]*15, "FOB Price": [0.0]*15, "Origin": [""]*15, "Availability": ["Prompt"]*15, "Ship Time": ["Prompt"]*15}), use_container_width=True, num_rows="dynamic", key=f"m_edit_{current_profile}")
    with col_b:
        st.subheader("Specialty Items")
        s_data = saved_data.get("spec_table_data")
        df_spec = st.data_editor(pd.DataFrame(s_data) if s_data else pd.DataFrame({"Product": [""]*10, "FOB Price": [0.0]*10, "Origin": [""]*10, "Availability": ["Prompt"]*10, "Ship Time": ["Prompt"]*10}), use_container_width=True, num_rows="dynamic", key=f"s_edit_{current_profile}")

    st.markdown("---")
    col_t1, col_t2 = st.columns(2)
    inc_m = col_t1.toggle("Include Standards", value=True)
    inc_s = col_t2.toggle("Include Specialties", value=True)
    
    btn1, btn2 = st.columns(2)
    if btn1.button(f"Generate Quote for {dest_city}", type="primary", use_container_width=True):
        st.session_state.pricing_txt = run_calculation(dest_city, df_master, df_spec, rate_map, round_val, inc_m, inc_s)
    if btn2.button("⚡ BULK QUOTE ALL LISTED CITIES", use_container_width=True):
        bulk_res = ""
        for c in active_cities:
            res = run_calculation(c, df_master, df_spec, rate_map, round_val, inc_m, inc_s)
            if res: bulk_res += res + "\n\n"
        st.session_state.pricing_txt = bulk_res

    if 'pricing_txt' in st.session_state:
        st.text_area("Report Output", value=st.session_state.pricing_txt, height=300)

    if st.sidebar.button("💾 SAVE PROFILE DATA"):
        config = {"states": states_input, "rates": rates_input, "sh_threshold": sh_threshold, "sh_floor": sh_floor, "uni_div": uni_div, "msr_div": msr_div, "round_to": round_val, "cities_list": cities_input, "master_table_data": df_master.to_dict('records'), "spec_table_data": df_spec.to_dict('records')}
        save_json(CONFIG_FILE, config)
        st.sidebar.success(f"Profile '{current_profile}' Saved!"); time.sleep(1); st.rerun()

# --- TAB 2: CRM & AUTO-DRAFT ---
with tab_customers:
    st.header(f"CRM: {current_profile}")
    if not os.path.exists(CUSTOMER_DB_FILE):
        pd.DataFrame(columns=["Company Name", "Buyer Email", "Location", "Notes"]).to_csv(CUSTOMER_DB_FILE, index=False)
    df_customers = pd.read_csv(CUSTOMER_DB_FILE)

    col_1, col_2 = st.columns([2, 1])

    with col_2:
        st.subheader("📬 Auto-Draft Bridge")
        target_cust = st.selectbox("Select Customer Profile", ["-- Select --"] + list(df_customers["Company Name"].unique()))
        if target_cust != "-- Select --":
            cust_row = df_customers[df_customers["Company Name"] == target_cust].iloc[0]
            email, loc = cust_row.get("Buyer Email", ""), cust_row.get("Location", "")
            if email and loc:
                with st.spinner(f"Pricing for {loc}..."):
                    auto_quote = run_calculation(loc, df_master, df_spec, rate_map, round_val, True, True)
                if auto_quote:
                    mailto = f"mailto:{email}?subject={urllib.parse.quote(f'Quote - {target_cust}')}&body={urllib.parse.quote(auto_quote)}"
                    st.markdown(f'<a href="{mailto}" target="_blank" style="text-decoration:none;"><div style="background-color:#0078d4;color:white;padding:15px;text-align:center;border-radius:8px;font-weight:bold;">🚀 OPEN EMAIL DRAFT</div></a>', unsafe_allow_html=True)
                    st.text_area("Preview Quote Body:", value=auto_quote, height=200)
            else: st.error("Missing Email or Location in CRM.")

    with col_1:
        st.subheader("📝 Master Directory")
        # Fix column alignment if missing
        for col in ["Company Name", "Buyer Email", "Location", "Notes"]:
            if col not in df_customers.columns: df_customers[col] = ""
        edited = st.data_editor(df_customers, use_container_width=True, num_rows="dynamic", key=f"crm_edit_{current_profile}")
        if st.button("💾 SAVE CRM CHANGES"):
            edited.to_csv(CUSTOMER_DB_FILE, index=False)
            st.success("CRM Updated!"); st.rerun()