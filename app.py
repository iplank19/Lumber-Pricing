import streamlit as st
import pandas as pd
import requests
import math
import json
import os
import time
import io
import zipfile

# --- APP UI SETUP ---
st.set_page_config(page_title="Lumber CRM & Pricing Master", layout="wide")

# --- FILE PATHS ---
CUSTOMER_DB_FILE = "customer_database.csv"
MATRIX_FILE = "customer_matrices.json"
MILEAGE_CACHE_FILE = "mileage_cache.json"

# --- MILEAGE CACHE LOGIC ---
def load_mileage_cache():
    if os.path.exists(MILEAGE_CACHE_FILE):
        with open(MILEAGE_CACHE_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_mileage_cache(cache):
    with open(MILEAGE_CACHE_FILE, "w") as f:
        json.dump(cache, f)

# Initialize mileage cache in session state for speed
if 'm_cache' not in st.session_state:
    st.session_state.m_cache = load_mileage_cache()

# --- PROFILE & CONFIG LOGIC ---
existing_profiles = [f.replace(".json", "") for f in os.listdir(".") if f.endswith(".json") and f != MILEAGE_CACHE_FILE and f != "customer_matrices.json"]
if not existing_profiles:
    existing_profiles = ["Default"]

st.sidebar.header("📁 Profile Manager")
selected_profile = st.sidebar.selectbox("Select Existing Profile", existing_profiles)
new_profile_name = st.sidebar.text_input("OR Create New Profile")
current_profile = new_profile_name if new_profile_name else selected_profile

def load_config(profile):
    filename = f"{profile}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f: return json.load(f)
    return None 

saved_data = load_config(current_profile) or {}

# --- SIDEBAR: 1. PRICING SETTINGS ---
st.sidebar.markdown("---")
st.sidebar.header("1. Pricing Settings")
states_input, rates_input = [], []
d_states = saved_data.get("states", ["", "", "", "", "", ""]) 
d_rates = saved_data.get("rates", [0.00] * 6) 

for i in range(1, 7):
    col_s, col_r = st.sidebar.columns([1, 2])
    s = col_s.text_input(f"St/Pr {i}", d_states[i-1] if i-1 < len(d_states) else "", key=f"s{i}_{current_profile}").upper().strip()
    r = col_r.number_input(f"Rate {i}", value=d_rates[i-1] if i-1 < len(d_rates) else 0.00, key=f"r{i}_{current_profile}")
    states_input.append(s); rates_input.append(r)
rate_map = {k: v for k, v in zip(states_input, rates_input) if k}

sh_threshold = st.sidebar.number_input("Short Haul Limit (Mi)", value=saved_data.get("sh_threshold", 200))
sh_floor = st.sidebar.number_input("Short Haul Floor ($)", value=saved_data.get("sh_floor", 700))
uni_div = st.sidebar.number_input("Std MBF Divisor", value=saved_data.get("uni_div", 23.0))
msr_div = st.sidebar.number_input("MSR MBF Divisor", value=saved_data.get("msr_div", 25.0))

round_options = [1, 5, 10, 0] 
round_val = st.sidebar.selectbox("Round Up To:", options=round_options, format_func=lambda x: {1: "Next $1", 5: "Next $5", 10: "Next $10", 0: "Exact"}[x], index=round_options.index(saved_data.get("round_to", 1)))

# --- SIDEBAR: 2. DESTINATIONS ---
st.sidebar.markdown("---")
st.sidebar.header("2. Destinations")
default_cities = "Chicago, IL\nHouston, TX\nAtlanta, GA\nToronto, ON"
saved_cities_raw = saved_data.get("cities_list", default_cities)
cities_input = st.sidebar.text_area("One City, ST per line", value=saved_cities_raw, height=180)
active_cities = [c.strip() for c in cities_input.split("\n") if c.strip()]

dest_city = st.sidebar.selectbox("Target for Single Quote", active_cities) if active_cities else "None"

# --- SIDEBAR: 3. BACKUP & EXPORT ---
st.sidebar.markdown("---")
st.sidebar.header("📥 Backup & Export Center")

def create_backup_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add core databases
        for f in [CUSTOMER_DB_FILE, MATRIX_FILE, MILEAGE_CACHE_FILE]:
            if os.path.exists(f):
                zf.write(f)
        # Add all user profiles
        for f in os.listdir("."):
            if f.endswith(".json") and f not in [MILEAGE_CACHE_FILE, MATRIX_FILE]:
                zf.write(f)
    return buf.getvalue()

st.sidebar.download_button(
    label="📦 DOWNLOAD SYSTEM BACKUP (ZIP)",
    data=create_backup_zip(),
    file_name=f"LumberHub_Backup_{time.strftime('%Y%m%d')}.zip",
    mime="application/zip",
    use_container_width=True
)

# --- NAVIGATION ---
tab_pricing, tab_customers = st.tabs(["🌲 Pricing Engine", "👥 Customer Matrix & CRM"])

# --- TAB 1: PRICING ENGINE ---
with tab_pricing:
    st.header(f"Pricing Portal: {current_profile}")
    
    col_m, col_s = st.columns(2)
    with col_m:
        st.subheader("Standard Offerings")
        saved_master = saved_data.get("master_table_data")
        df_master = st.data_editor(pd.DataFrame(saved_master) if saved_master else pd.DataFrame({"Product": [""]*30, "FOB Price": [0.0]*30, "Origin": [""]*30, "Availability": ["Prompt"]*30, "Ship Time": ["Prompt"]*30}), key=f"m_tab_{current_profile}", use_container_width=True, num_rows="dynamic")
    
    with col_s:
        st.subheader("Specialty Items")
        saved_spec = saved_data.get("spec_table_data")
        df_spec = st.data_editor(pd.DataFrame(saved_spec) if saved_spec else pd.DataFrame({"Product": [""]*10, "FOB Price": [0.0]*10, "Origin": [""]*10, "Availability": ["Prompt"]*10, "Ship Time": ["Prompt"]*10}), key=f"s_tab_{current_profile}", use_container_width=True, num_rows="dynamic")

    if st.sidebar.button("💾 SAVE PROFILE SETTINGS"):
        config = {
            "states": states_input, "rates": rates_input, "sh_threshold": sh_threshold, 
            "sh_floor": sh_floor, "uni_div": uni_div, "msr_div": msr_div, 
            "round_to": round_val, "cities_list": cities_input, 
            "master_table_data": df_master.to_dict('records'), 
            "spec_table_data": df_spec.to_dict('records')
        }
        with open(f"{current_profile}.json", "w") as f: json.dump(config, f)
        st.sidebar.success("Settings Saved!")
        time.sleep(1); st.rerun()

    # --- MILEAGE ENGINE WITH CACHING ---
    def get_miles(origin, destination):
        if not origin or not destination: return None
        lane_key = f"{origin.strip().upper()} to {destination.strip().upper()}"
        
        if lane_key in st.session_state.m_cache:
            return st.session_state.m_cache[lane_key]
        
        time.sleep(1.2) # API Rate Limit protection
        try:
            headers = {'User-Agent': 'lumber_hub_master_v1'}
            res_a = requests.get(f"https://nominatim.openstreetmap.org/search?q={origin.strip()}&format=json&limit=1", headers=headers).json()
            res_b = requests.get(f"https://nominatim.openstreetmap.org/search?q={destination.strip()}&format=json&limit=1", headers=headers).json()
            c_a = (res_a[0]['lon'], res_a[0]['lat']); c_b = (res_b[0]['lon'], res_b[0]['lat'])
            r_url = f"http://router.project-osrm.org/route/v1/driving/{c_a[0]},{c_a[1]};{c_b[0]},{c_b[1]}?overview=false"
            miles = requests.get(r_url).json()['routes'][0]['distance'] * 0.000621371
            
            st.session_state.m_cache[lane_key] = miles
            save_mileage_cache(st.session_state.m_cache)
            return miles
        except: return None

    def run_report(cities, show_bulk, show_spec, round_rule):
        out = ""
        combined = pd.concat([df_master if show_bulk else pd.DataFrame(), df_spec if show_spec else pd.DataFrame()])
        combined = combined[combined['FOB Price'] > 0]
        
        for city in cities:
            rows = []
            for _, r in combined.iterrows():
                origin = str(r.get('Origin', '')).strip().upper()
                rate = next((v for k, v in rate_map.items() if k in origin), None)
                if rate is None: continue
                
                miles = get_miles(origin, city)
                if miles:
                    cost = sh_floor if miles < sh_threshold else miles * rate
                    div = msr_div if "MSR" in str(r['Product']).upper() else uni_div
                    raw = r['FOB Price'] + (cost / div)
                    p = math.ceil(raw / round_rule) * round_rule if round_rule > 0 else round(raw, 2)
                    rows.append(f"{str(r['Product'])[:28]:<28} {str(r['Availability'])[:12]:<12} ${p:>7}")
            
            if rows:
                header = f"{'PRODUCT':<28} {'AVAIL':<12} {'PRICE':>8}"
                out += f"QUOTE - {city.upper()}\n{header}\n{'-'*60}\n" + "\n".join(rows) + "\n\n"
        return out

    st.markdown("---")
    col_t1, col_t2 = st.columns(2)
    s_bulk = col_t1.toggle("Include Standards", value=True)
    s_spec = col_t2.toggle("Include Specialties", value=True)
    
    col_b1, col_b2 = st.columns(2)
    if col_b1.button(f"Generate Quote for {dest_city}", type="primary", use_container_width=True):
        st.session_state.txt = run_report([dest_city], s_bulk, s_spec, round_val)
    if col_b2.button("⚡ BULK QUOTE ALL LISTED CITIES", use_container_width=True):
        st.session_state.txt = run_report(active_cities, s_bulk, s_spec, round_val)

    if 'txt' in st.session_state:
        st.text_area("Final Report Output", value=st.session_state.txt, height=400)
        st.caption(f"📍 Mileage cache: {len(st.session_state.m_cache)} active lanes.")

# --- TAB 2: CRM & MATRIX ---
with tab_customers:
    st.header("👥 Customer Matrix & CRM")
    if not os.path.exists(CUSTOMER_DB_FILE):
        pd.DataFrame(columns=["Company Name", "Buyer Info", "Location(s)", "Notes"]).to_csv(CUSTOMER_DB_FILE, index=False)
    df_customers = pd.read_csv(CUSTOMER_DB_FILE)
    
    if os.path.exists(MATRIX_FILE):
        with open(MATRIX_FILE, "r") as f: all_matrices = json.load(f)
    else: all_matrices = {}

    target_customer = st.selectbox("Select Customer to View Matrix", ["-- Select --"] + list(df_customers["Company Name"].unique()))

    if target_customer != "-- Select --":
        cust_key = target_customer.replace(" ", "_")
        current_matrix = all_matrices.get(cust_key, {})
        st.subheader(f"📊 Buy Matrix: {target_customer}")
        widths = ["2x4", "2x6", "2x8", "2x10", "2x12"]; grades = ["#1", "#2", "#3", "MSR"]; lengths = ["8'", "10'", "12'", "14'", "16'", "18'", "20'"]
        
        updated_matrix = {}
        for grade in grades:
            with st.expander(f"Grade: {grade}", expanded=(grade=="#2")):
                grade_data = current_matrix.get(grade, {}); updated_matrix[grade] = {}
                cols = st.columns([1] + [1]*len(lengths))
                for i, l in enumerate(lengths): cols[i+1].write(f"**{l}**")
                for w in widths:
                    cols = st.columns([1] + [1]*len(lengths))
                    cols[0].write(f"**{w}**"); updated_matrix[grade][w] = []
                    saved_lengths = grade_data.get(w, [])
                    for i, l in enumerate(lengths):
                        if cols[i+1].checkbox("", key=f"cb_{cust_key}_{grade}_{w}_{l}", value=(l in saved_lengths)):
                            updated_matrix[grade][w].append(l)
        
        if st.button("💾 SAVE CUSTOMER MATRIX"):
            all_matrices[cust_key] = updated_matrix
            with open(MATRIX_FILE, "w") as f: json.dump(all_matrices, f)
            st.success(f"Matrix for {target_customer} Saved!")

    st.markdown("---")
    st.subheader("📝 Master Customer Directory")
    df_display = df_customers.copy()
    for col in ["Company Name", "Buyer Info", "Location(s)", "Notes"]:
        if col not in df_display.columns: df_display[col] = ""
    
    edited_df = st.data_editor(df_display, use_container_width=True, num_rows="dynamic", key="main_db_editor")
    
    if st.button("💾 Update Customer List"):
        edited_df.to_csv(CUSTOMER_DB_FILE, index=False)
        st.success("List Updated!"); st.rerun()