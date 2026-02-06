import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta, timezone
import time

# ==========================================
# 1. ตั้งค่าระบบและฐานข้อมูล
# ==========================================
st.set_page_config(page_title="Inventory & Chemical System", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'inventory_final.db')

# 🔥 ค่าคงที่สำหรับสารเคมี (Chemical Config)
CHEMICAL_CONFIG = {
    "NaOH":   {"capacity": 60000, "limit": 48000, "density": 1.52, "name": "Sodium Hydroxide (โซดาไฟ 50%)"},
    "H2SO4":  {"capacity": 60000, "limit": 48000, "density": 1.84, "name": "Sulfuric Acid (กรดซัลฟิวริก 98%)"},
    "HCl":    {"capacity": 60000, "limit": 48000, "density": 1.18, "name": "Hydrochloric Acid (กรดเกลือ 35%)"},
    "H2O2":   {"capacity": 30000, "limit": 24000, "density": 1.20, "name": "Hydrogen Peroxide (ไฮโดรเจนเปอร์ออกไซด์ 50%)"}
}

def get_thai_now():
    tz_thai = timezone(timedelta(hours=7))
    return datetime.now(tz_thai)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            item_code TEXT,
            item_name TEXT,
            action_type TEXT,
            quantity REAL,
            unit TEXT,
            category TEXT,
            expiry_date TEXT,
            department TEXT,
            requester TEXT,
            remark TEXT,
            upload_time TEXT 
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS chemical_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            chem_code TEXT,
            action_type TEXT,
            qty_kg REAL,
            qty_l REAL,
            density REAL,
            remark TEXT,
            upload_time TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- ฟังก์ชันจัดการวัสดุทั่วไป (General) ---
def save_to_db(df, action_type):
    if df.empty: return
    conn = sqlite3.connect(DB_NAME)
    try:
        df['action_type'] = action_type
        batch_timestamp = get_thai_now().strftime('%Y-%m-%d %H:%M:%S')
        df['upload_time'] = batch_timestamp
        for col in ['date', 'expiry_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
        if 'item_code' in df.columns:
            df['item_code'] = df['item_code'].fillna('-')
        df.to_sql('transactions', conn, if_exists='append', index=False)
        st.success(f"✅ บันทึกวัสดุทั่วไป (Material) เรียบร้อย! ({len(df)} รายการ)")
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Error Material: {e}")
    finally: conn.close()

# --- ฟังก์ชันจัดการสารเคมี (Chemical Batch) ---
def save_chem_batch(df, action_type):
    if df.empty: return
    conn = sqlite3.connect(DB_NAME)
    try:
        batch_timestamp = get_thai_now().strftime('%Y-%m-%d %H:%M:%S')
        
        # เตรียมข้อมูลสำหรับบันทึก
        records = []
        for _, row in df.iterrows():
            code = str(row['chem_code']).strip()
            kg = float(row['qty_kg'])
            date = pd.to_datetime(row['date']).strftime('%Y-%m-%d')
            remark = str(row.get('remark', ''))
            
            # หาค่า Density
            density = 1.0
            if code in CHEMICAL_CONFIG:
                density = CHEMICAL_CONFIG[code]['density']
            
            qty_l = kg / density if density > 0 else 0
            
            records.append((date, code, action_type, kg, qty_l, density, remark, batch_timestamp))
            
        conn.executemany('''
            INSERT INTO chemical_transactions (date, chem_code, action_type, qty_kg, qty_l, density, remark, upload_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', records)
        
        conn.commit()
        st.success(f"✅ บันทึกสารเคมี (Chemical) เรียบร้อย! ({len(records)} รายการ)")
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Error Chemical: {e}")
    finally: conn.close()

def load_data():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC, id DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def load_chem_data():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM chemical_transactions ORDER BY date DESC, id DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def calculate_inventory(df):
    if df.empty: return pd.DataFrame()
    df['item_code'] = df['item_code'].astype(str)
    df['item_name'] = df['item_name'].astype(str)
    bal = df.pivot_table(index=['item_code','item_name'], columns='action_type', values='quantity', aggfunc='sum', fill_value=0).reset_index()
    latest = df.sort_values('date', ascending=False).drop_duplicates(['item_code','item_name'])
    cats = df[(df['category'].notna()) & (~df['category'].isin(['','-','None']))]
    best_cat = cats.sort_values('date',ascending=False).drop_duplicates(['item_code','item_name'])[['item_code','item_name','category']] if not cats.empty else pd.DataFrame(columns=['item_code','item_name','category'])
    exps = df[(df['action_type']=='In') & df['expiry_date'].notna()]
    min_exp = exps.groupby(['item_code','item_name'])['expiry_date'].min().reset_index() if not exps.empty else pd.DataFrame(columns=['item_code','item_name','expiry_date'])
    bal = bal.merge(latest[['item_code','item_name','unit']], on=['item_code','item_name'], how='left').merge(best_cat, on=['item_code','item_name'], how='left').merge(min_exp, on=['item_code','item_name'], how='left')
    bal['category'] = bal['category'].fillna('-')
    bal['unit'] = bal['unit'].fillna('')
    if 'In' not in bal: bal['In']=0
    if 'Out' not in bal: bal['Out']=0
    bal['Balance'] = bal['In'] - bal['Out']
    return bal

def calculate_chem_balance(df):
    if df.empty: return {}
    bal = df.pivot_table(index='chem_code', columns='action_type', values='qty_kg', aggfunc='sum', fill_value=0)
    if 'In' not in bal: bal['In'] = 0
    if 'Out' not in bal: bal['Out'] = 0
    bal['Balance_KG'] = bal['In'] - bal['Out']
    return bal['Balance_KG'].to_dict()

def delete_batch(batch):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM transactions WHERE upload_time = ?", (batch,))
    conn.execute("DELETE FROM chemical_transactions WHERE upload_time = ?", (batch,))
    conn.commit()
    conn.close()
    st.success(f"ลบรอบ {batch} สำเร็จ"); st.cache_data.clear()

def delete_data(ids, table='transactions'):
    conn = sqlite3.connect(DB_NAME)
    conn.execute(f"DELETE FROM {table} WHERE id IN {tuple(ids) if len(ids)>1 else f'({ids[0]})'}")
    conn.commit()
    conn.close()
    st.success("ลบรายการสำเร็จ"); st.cache_data.clear()

# ==========================================
# 2. ส่วน UI หลัก
# ==========================================
init_db()

st.sidebar.title("🔐 เข้าสู่ระบบ")
role = st.sidebar.radio("เลือกแผนกที่ใช้งาน:", ["👤 Other Department", "🔑 Material Control Department"])
is_admin = False
if role == "🔑 Material Control Department":
    st.sidebar.markdown("---")
    password = st.sidebar.text_input("รหัสผ่านแผนก:", type="password")
    if password == "1234":
        is_admin = True
        st.sidebar.success("ยืนยันตัวตนสำเร็จ ✅")
    elif password: st.sidebar.error("รหัสผิด ❌")

if is_admin:
    menu_options = [
        "📊 Dashboard & แจ้งเตือน", 
        "🧪 ระบบจัดการสารเคมี (Chemical Tanks)", 
        "📋 วัสดุทั้งหมด (Overview)",
        "📉 วัสดุหมดสต๊อก (Out of Stock)",
        "🔍 ค้นหา (Search)",   
        "📅 รายงานประจำวัน (Daily)", 
        "📥 รับเข้า (In)", 
        "📤 เบิกออก (Out)", 
        "🔧 จัดการข้อมูล"
    ]
else:
    menu_options = [
        "🧪 ระบบจัดการสารเคมี (Chemical Tanks)", 
        "📋 วัสดุทั้งหมด (Overview)", 
        "📉 วัสดุหมดสต๊อก (Out of Stock)",
        "🔍 ค้นหา (Search)"
    ]

st.sidebar.markdown("---")
choice = st.sidebar.radio("เมนู:", menu_options)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 รีเฟรชข้อมูล"): st.rerun()

# โหลดข้อมูล
df = load_data()
balance_df = calculate_inventory(df) if not df.empty else pd.DataFrame()
chem_df = load_chem_data()
chem_bal = calculate_chem_balance(chem_df)

# ==========================================
# 3. ส่วนเนื้อหา (Content)
# ==========================================

# --- 🧪 สารเคมี (Chemical) ---
if choice == "🧪 ระบบจัดการสารเคมี (Chemical Tanks)":
    st.header("🧪 ระบบจัดการสารเคมี (Chemical Tank Management)")
    
    st.subheader("📊 สถานะถังเก็บปัจจุบัน (Tank Status)")
    cols = st.columns(4)
    for i, (code, conf) in enumerate(CHEMICAL_CONFIG.items()):
        current_kg = chem_bal.get(code, 0)
        current_l = current_kg / conf['density']
        percent = (current_kg / conf['limit']) * 100
        with cols[i]:
            st.markdown(f"#### {code}")
            st.caption(conf['name'])
            safe_pct = max(0.0, min(percent/100, 1.0))
            if current_kg > conf['limit']: st.progress(safe_pct, text="⚠️ OVER")
            elif current_kg > conf['limit']*0.9: st.progress(safe_pct, text="🟠 Warning")
            else: st.progress(safe_pct, text="🟢 Normal")
            st.metric("คงเหลือ", f"{current_kg:,.0f} KG", f"{current_l:,.0f} L")
            st.caption(f"Limit: {conf['limit']:,} KG")
            st.divider()

    if is_admin:
        st.markdown("---")
        st.subheader("📜 ประวัติการรับ/จ่ายสารเคมี (History)")
        if not chem_df.empty:
            csv = chem_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลดประวัติ (CSV)", csv, "chem_history.csv", "text/csv")
            st.dataframe(chem_df[['date', 'chem_code', 'action_type', 'qty_kg', 'qty_l', 'remark']], use_container_width=True, hide_index=True)
        else: st.info("ยังไม่มีประวัติรายการ")

# --- 📊 Dashboard ---
elif choice == "📊 Dashboard & แจ้งเตือน" and is_admin:
    st.header("📊 Dashboard ภาพรวมสต็อก")
    if not balance_df.empty:
        today = get_thai_now().strftime('%Y-%m-%d')
        next_30 = (get_thai_now() + timedelta(days=30)).strftime('%Y-%m-%d')
        has_exp = balance_df[balance_df['expiry_date'].notna() & (balance_df['Balance']>0)]
        expired = has_exp[has_exp['expiry_date'] < today]
        near = has_exp[(has_exp['expiry_date'] >= today) & (has_exp['expiry_date'] <= next_30)]
        c1, c2 = st.columns(2)
        with c1:
            if not expired.empty: st.error(f"⛔ หมดอายุแล้ว ({len(expired)} รายการ)"); st.dataframe(expired[['expiry_date','item_name','Balance']], hide_index=True)
            else: st.success("✅ ไม่มีของหมดอายุ")
        with c2:
            if not near.empty: st.warning(f"⚠️ ใกล้หมดอายุ ({len(near)} รายการ)"); st.dataframe(near[['expiry_date','item_name','Balance']], hide_index=True)
            else: st.success("✅ ไม่มีของใกล้หมดอายุ")
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("📦 รายการวัสดุ", len(balance_df))
        c2.metric("⚠️ สินค้าหมด", len(balance_df[balance_df['Balance']<=0]))
        c3.metric("📅 เวลาปัจจุบัน", get_thai_now().strftime("%H:%M:%S"))
    else: st.info("ยังไม่มีข้อมูล")

# --- 📋 วัสดุทั้งหมด ---
elif choice == "📋 วัสดุทั้งหมด (Overview)":
    st.header("📋 รายการวัสดุคงเหลือทั้งหมด")
    if not balance_df.empty:
        c1, c2 = st.columns([2,1])
        with c1: txt = st.text_input("🔍 ค้นหา:", placeholder="ชื่อ หรือ รหัส...")
        with c2: 
            cats = ["ทั้งหมด"] + sorted([c for c in balance_df['category'].unique() if c!='-'])
            sel = st.selectbox("หมวดหมู่:", cats)
        show = balance_df.copy()
        if sel != "ทั้งหมด": show = show[show['category']==sel]
        if txt: show = show[show.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)]
        if is_admin:
            csv = show.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลด (CSV)", csv, "stock_overview.csv", "text/csv", type="primary")
        else: st.caption("ℹ️ เฉพาะ Admin เท่านั้นที่ดาวน์โหลดได้")
        st.dataframe(show[['item_code','item_name','category','In','Out','Balance','unit','expiry_date']], use_container_width=True, hide_index=True)
    else: st.info("ไม่มีข้อมูล")

# --- 📉 วัสดุหมดสต๊อก ---
elif choice == "📉 วัสดุหมดสต๊อก (Out of Stock)":
    st.header("📉 รายงานวัสดุที่ถูกเบิกจ่ายหมดแล้ว (Balance ≤ 0)")
    if not balance_df.empty:
        out = balance_df[balance_df['Balance'] <= 0]
        if not out.empty:
            if is_admin:
                csv = out.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 ดาวน์โหลด (CSV)", csv, "out_of_stock.csv", "text/csv", type="primary")
            st.dataframe(out[['item_code','item_name','category','Balance','unit']], use_container_width=True, hide_index=True)
        else: st.success("✅ เยี่ยมมาก! ไม่มีรายการวัสดุหมดสต๊อก")
    else: st.info("ไม่มีข้อมูล")

# --- 🔍 ค้นหา ---
elif choice == "🔍 ค้นหา (Search)":
    st.header("🔍 ค้นหาประวัติรายตัว")
    if not df.empty:
        txt = st.text_input("พิมพ์รหัส/ชื่อ:", key="search")
        if txt:
            res = df[df.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)]
            if not res.empty:
                if is_admin:
                    in_s = res[res['action_type']=='In']['quantity'].sum()
                    out_s = res[res['action_type']=='Out']['quantity'].sum()
                    st.markdown(f"**สรุป:** รับ {in_s:,.2f} | จ่าย {out_s:,.2f} | คงเหลือ {in_s-out_s:,.2f}")
                    st.dataframe(res, use_container_width=True, hide_index=True)
                else:
                    summary = calculate_inventory(res)
                    for i, r in summary.iterrows():
                        st.markdown(f"**{r['item_name']}** (Code: {r['item_code']})")
                        st.write(f"คงเหลือ: {r['Balance']:,.2f} {r['unit']}")
                        st.divider()
            else: st.warning("ไม่พบ")
    else: st.info("ไม่มีข้อมูล")

# --- 📅 รายงานประจำวัน ---
elif choice == "📅 รายงานประจำวัน (Daily)" and is_admin:
    st.header("📅 รายงานประจำวัน (รวม Material & Chemical)")
    # Report for Material
    st.subheader("1. วัสดุทั่วไป (Material)")
    if not df.empty:
        date = st.date_input("เลือกวันที่:", get_thai_now()).strftime('%Y-%m-%d')
        daily_mat = df[df['date'] == date]
        if not daily_mat.empty:
            st.dataframe(daily_mat, use_container_width=True, hide_index=True)
        else: st.info("ไม่มีรายการวัสดุวันนี้")
    
    # Report for Chemical
    st.subheader("2. สารเคมี (Chemical)")
    if not chem_df.empty:
        daily_chem = chem_df[chem_df['date'] == date]
        if not daily_chem.empty:
            st.dataframe(daily_chem, use_container_width=True, hide_index=True)
        else: st.info("ไม่มีรายการสารเคมีวันนี้")

# --- 📥 รับเข้า (In) ---
elif choice == "📥 รับเข้า (In)" and is_admin:
    st.header("📥 รับเข้า (Multi-Sheet Support)")
    st.info("💡 ไฟล์ Excel ต้องมี Sheet ชื่อ: 'Material' หรือ 'Chemical Tank'")
    
    f = st.file_uploader("Upload ไฟล์ (In)", type=['xlsx'], key='in')
    if f:
        xls = pd.ExcelFile(f)
        sheet_names = xls.sheet_names
        st.write(f"📂 พบ Sheet: {sheet_names}")
        
        # 1. Process Material
        if 'Material' in sheet_names:
            st.subheader("📦 พบข้อมูล Material")
            d_mat = pd.read_excel(f, sheet_name='Material')
            cmap = {'วันที่':'date', 'รหัสวัสดุ':'item_code', 'ชื่อรายการ':'item_name', 
                    'จำนวน':'quantity', 'หน่วย':'unit', 'วันหมดอายุ':'expiry_date', 
                    'ประเภท':'category', 'หมายเหตุ':'remark'}
            # ลอง map ชื่อคอลัมน์ (ถ้าตรง)
            d_mat = d_mat.rename(columns=cmap)
            st.dataframe(d_mat.head(3))
            if st.button("✅ บันทึก Material", key="btn_mat_in"):
                req = ['date','item_code','item_name','quantity','unit','expiry_date','category','remark']
                for c in req: 
                    if c not in d_mat.columns: d_mat[c] = None
                save_to_db(d_mat[req], 'In')
        
        # 2. Process Chemical
        if 'Chemical Tank' in sheet_names:
            st.subheader("🧪 พบข้อมูล Chemical Tank")
            d_chem = pd.read_excel(f, sheet_name='Chemical Tank')
            # คาดหวังคอลัมน์: วันที่, รหัสสารเคมี, จำนวน KG, หมายเหตุ
            cmap_chem = {'วันที่':'date', 'รหัสสารเคมี':'chem_code', 'จำนวน KG':'qty_kg', 'หมายเหตุ':'remark'}
            d_chem = d_chem.rename(columns=cmap_chem)
            st.dataframe(d_chem.head(3))
            if st.button("✅ บันทึก Chemical", key="btn_chem_in"):
                # ตรวจสอบว่ามีคอลัมน์ครบไหม
                if 'chem_code' in d_chem.columns and 'qty_kg' in d_chem.columns:
                    save_chem_batch(d_chem, 'In')
                else:
                    st.error("❌ ข้อมูล Chemical ไม่ถูกต้อง (ต้องมี: รหัสสารเคมี, จำนวน KG)")

# --- 📤 เบิกออก (Out) ---
elif choice == "📤 เบิกออก (Out)" and is_admin:
    st.header("📤 เบิกออก (Multi-Sheet Support)")
    st.info("💡 ไฟล์ Excel ต้องมี Sheet ชื่อ: 'Material' หรือ 'Chemical Tank'")
    
    f = st.file_uploader("Upload ไฟล์ (Out)", type=['xlsx'], key='out')
    if f:
        xls = pd.ExcelFile(f)
        sheet_names = xls.sheet_names
        
        # 1. Process Material
        if 'Material' in sheet_names:
            st.subheader("📦 พบข้อมูล Material (เบิกออก)")
            d_mat = pd.read_excel(f, sheet_name='Material')
            # Map คอลัมน์สำหรับเบิกออก (อาจมี แผนก, ผู้เบิก)
            cmap = {'วันที่':'date', 'รหัสวัสดุ':'item_code', 'ชื่อรายการ':'item_name', 
                    'จำนวน':'quantity', 'หน่วย':'unit', 'แผนก':'department', 
                    'ผู้เบิก':'requester', 'ประเภท':'category', 'หมายเหตุ':'remark'}
            d_mat = d_mat.rename(columns=cmap)
            st.dataframe(d_mat.head(3))
            if st.button("✅ บันทึก Material (Out)", key="btn_mat_out"):
                req = ['date','item_code','item_name','quantity','unit','department','requester','category','remark']
                for c in req: 
                    if c not in d_mat.columns: d_mat[c] = None
                save_to_db(d_mat[req], 'Out')
        
        # 2. Process Chemical
        if 'Chemical Tank' in sheet_names:
            st.subheader("🧪 พบข้อมูล Chemical Tank (เบิกออก)")
            d_chem = pd.read_excel(f, sheet_name='Chemical Tank')
            cmap_chem = {'วันที่':'date', 'รหัสสารเคมี':'chem_code', 'จำนวน KG':'qty_kg', 'หมายเหตุ':'remark'}
            d_chem = d_chem.rename(columns=cmap_chem)
            st.dataframe(d_chem.head(3))
            if st.button("✅ บันทึก Chemical (Out)", key="btn_chem_out"):
                if 'chem_code' in d_chem.columns and 'qty_kg' in d_chem.columns:
                    save_chem_batch(d_chem, 'Out')
                else:
                    st.error("❌ ข้อมูล Chemical ไม่ถูกต้อง")

# --- 🔧 จัดการข้อมูล ---
elif choice == "🔧 จัดการข้อมูล" and is_admin:
    st.header("🔧 จัดการข้อมูล")
    # รวม 2 ตาราง
    if not df.empty or not chem_df.empty:
        t1, t2 = st.tabs(["ลบรอบอัปโหลด", "ลบรายรายการ"])
        with t1:
            # รวม Timestamp จากทั้ง 2 ตาราง
            times1 = df['upload_time'].unique().tolist() if 'upload_time' in df else []
            times2 = chem_df['upload_time'].unique().tolist() if 'upload_time' in chem_df else []
            all_times = sorted(list(set(times1 + times2)), reverse=True)
            
            sel = st.selectbox("เลือกรอบเวลา:", all_times)
            if st.button("🗑️ ลบข้อมูลรอบนี้"): delete_batch(sel); st.rerun()
        
        with t2:
            st.write("เลือกตารางที่จะลบ:")
            table_sel = st.radio("ตาราง:", ["Material", "Chemical"])
            if table_sel == "Material":
                st.dataframe(df)
                ids = st.multiselect("Select ID:", df['id'])
                if st.button("ลบ Material"): delete_data(ids, 'transactions'); st.rerun()
            else:
                st.dataframe(chem_df)
                ids = st.multiselect("Select ID:", chem_df['id'])
                if st.button("ลบ Chemical"): delete_data(ids, 'chemical_transactions'); st.rerun()