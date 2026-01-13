import streamlit as st
import pandas as pd
import requests
import math
import json
import os
import time

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

# --- SIDEBAR: STATE RATES ---
st.sidebar.header("1. State/Prov Rates")
states_input, rates_input = [], []
d_states = saved_data.get("states", ["", "", "", "", "", ""]) 
d_rates = saved_data.get("rates", [0.00] * 6) 

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St/Pr {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = dict(zip(states_input, rates_input))

# --- SIDEBAR: LOGISTICS & ROUNDING ---
st.sidebar.markdown("---")
st.sidebar.header("2. Logistics & Rounding")
sh_threshold = st.sidebar.number_input("Short Haul Limit (Miles)", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor ($)", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Std MBF per Truck", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR MBF per Truck", value=saved_data.get("msr_div", 25.0))

# Adjustable Rounding Rule
round_options = [1, 5, 10, 0] 
round_labels = {1: "Next $1", 5: "Next $5", 10: "Next $10", 0: "Exact (Decimals)"}
round_val = st.sidebar.selectbox("Round Up To:", options=round_options, 
                                 format_func=lambda x: round_labels[x],
                                 index=round_options.index(saved_data.get("round_to", 1)))

# --- SIDEBAR: DESTINATIONS ---
st.sidebar.markdown("---")
st.sidebar.header("3. Destinations")
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
        "states": states_input, "rates": rates_input, 
        "sh_threshold": sh_threshold, "sh_floor": sh_floor,
        "uni_div": uni_div, "msr_div": msr_div,
        "round_to": round_val,
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
        headers = {'User-Agent': 'lumber_v20'}
        url_a = f"https://nominatim.openstreetmap.org/search?q={origin}&format=json&limit=1"
        url_b = f"https://nominatim.openstreetmap.org/search?q={destination}&format=json&limit=1"
        res_a = requests.get(url_a, headers=headers).json()
        res_b = requests.get(url_b, headers=headers).json()
        c_a = (res_a[0]['lon'], res_a[0]['lat']); c_b = (res_b[0]['lon'], res_b[0]['lat'])
        r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
        return requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
    except: return None

def run_report(cities, spec_only, round_rule):
    out = ""
    combined = df_spec if spec_only else pd.concat([df_master, df_spec])
    for city in cities:
        rows = []
        for _, r in combined.iterrows():
            if float(r['FOB Price']) > 0 and str(r['Product']).strip():
                rate = next((v for k, v in rate_map.items() if k and k in str(r['Origin']).upper()), 0.0)
                miles = get_miles(r['Origin'], city)
                if miles:
                    cost = sh_floor if miles < sh_threshold else miles * rate
                    div = msr_div if "MSR" in str(r['Product']).upper() else uni_div
                    raw_price = r['FOB Price'] + (cost / div)
                    
                    if round_rule == 0:
                        p = round(raw_price, 2)
                    else:
                        p = math.ceil(raw_price / round_rule) * round_rule
                        
                    rows.append(f"{r['Product']:<25} {r['Availability']:<10} {r['Ship Time']:<10} ${p}")
        if rows:
            out += f"LUMBER QUOTE - {city.upper()}\n{'PRODUCT':<25} {'AVAIL':<10} {'SHIP':<10} {'PRICE'}\n" + "-"*55 + "\n" + "\n".join(rows) + "\n\n"
    return out

# --- OUTPUT ---
st.markdown("---")
s_only = st.toggle("Specialty Items ONLY")
col1, col2 = st.columns(2)

if col1.button(f"Generate Quote for {dest_city}", type="primary", use_container_width=True):
    st.session_state.txt = run_report([dest_city], s_only, round_val)

if col2.button("⚡ BULK ALL CITIES", use_container_width=True):
    st.session_state.txt = run_report(city_list, s_only, round_val)

if 'txt' in st.session_state:
    st.subheader("📋 Final Quote (Copy & Paste)")
    st.text_area("Quote Content", value=st.session_state.txt, height=400)
    st.info("💡 Use Ctrl+A and Ctrl+C to quickly copy this report into an email.")