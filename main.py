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

# 🔥 ค่าคงที่สำหรับสารเคมี (Config)
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
    # ตารางวัสดุทั่วไป
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
    # ตารางสารเคมี (แยกใหม่)
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

# --- ฟังก์ชันจัดการวัสดุทั่วไป ---
def save_to_db(df, action_type):
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
        st.success(f"✅ บันทึกข้อมูล '{action_type}' เรียบร้อย!")
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Error: {e}")
    finally: conn.close()

def load_data():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC, id DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def enrich_transactions(df):
    if df.empty: return df
    ref_df = df[df['category'].notna() & (~df['category'].isin(['','-']))]
    if not ref_df.empty:
        ref_map = ref_df.sort_values('date', ascending=False).drop_duplicates('item_code').set_index('item_code')['category']
        df['category'] = df['category'].fillna(df['item_code'].map(ref_map))
    return df

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

def delete_data(ids):
    conn = sqlite3.connect(DB_NAME)
    conn.execute(f"DELETE FROM transactions WHERE id IN {tuple(ids) if len(ids)>1 else f'({ids[0]})'}")
    conn.commit()
    conn.close()
    st.success("ลบข้อมูลสำเร็จ"); st.cache_data.clear()

def delete_batch(batch):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM transactions WHERE upload_time = ?", (batch,))
    conn.commit()
    conn.close()
    st.success(f"ลบรอบ {batch} สำเร็จ"); st.cache_data.clear()

# --- ฟังก์ชันจัดการสารเคมี (Chemical Functions) ---
def save_chem_transaction(date, code, action, kg, density, remark):
    conn = sqlite3.connect(DB_NAME)
    try:
        liters = kg / density if density > 0 else 0
        now = get_thai_now().strftime('%Y-%m-%d %H:%M:%S')
        sql = '''INSERT INTO chemical_transactions (date, chem_code, action_type, qty_kg, qty_l, density, remark, upload_time)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)'''
        conn.execute(sql, (date, code, action, kg, liters, density, remark, now))
        conn.commit()
        st.success(f"✅ บันทึก {action} {code}: {kg} KG ({liters:.2f} L) เรียบร้อย")
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Error: {e}")
    finally: conn.close()

def load_chem_data():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM chemical_transactions ORDER BY date DESC, id DESC", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def calculate_chem_balance(df):
    if df.empty: return {}
    bal = df.pivot_table(index='chem_code', columns='action_type', values='qty_kg', aggfunc='sum', fill_value=0)
    if 'In' not in bal: bal['In'] = 0
    if 'Out' not in bal: bal['Out'] = 0
    bal['Balance_KG'] = bal['In'] - bal['Out']
    return bal['Balance_KG'].to_dict()

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

# --- เมนู ---
if is_admin:
    menu_options = [
        "📊 Dashboard & แจ้งเตือน", 
        "🧪 ระบบจัดการสารเคมี (Chemical Tanks)",  # <--- เมนูใหม่
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
        "🧪 ระบบจัดการสารเคมี (Chemical Tanks)",  # <--- เมนูใหม่
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

# ==========================================
# 3. ส่วนเนื้อหา (แยกตามเมนู)
# ==========================================

# --- 🧪 ระบบจัดการสารเคมี (Chemical Tanks) ---
if choice == "🧪 ระบบจัดการสารเคมี (Chemical Tanks)":
    st.header("🧪 ระบบจัดการสารเคมี (Chemical Tank Management)")
    
    # 1. โหลดและคำนวณยอด
    chem_df = load_chem_data()
    chem_bal = calculate_chem_balance(chem_df)
    
    # 2. แสดง Dashboard ถังเก็บ (Card View)
    st.subheader("📊 สถานะถังเก็บปัจจุบัน (Tank Status)")
    cols = st.columns(4)
    
    for i, (code, conf) in enumerate(CHEMICAL_CONFIG.items()):
        current_kg = chem_bal.get(code, 0)
        current_l = current_kg / conf['density']
        percent = (current_kg / conf['limit']) * 100
        
        with cols[i]:
            st.markdown(f"#### {code}")
            st.caption(conf['name'])
            
            # Progress Bar (เทียบกับ Limit การเติม)
            safe_pct = min(percent/100, 1.0)
            if current_kg > conf['limit']:
                st.progress(safe_pct, text="⚠️ OVER LIMIT")
            elif current_kg > conf['limit'] * 0.9:
                st.progress(safe_pct, text="🟠 Warning")
            else:
                st.progress(safe_pct, text="🟢 Normal")
                
            st.metric("ปริมาณคงเหลือ", f"{current_kg:,.0f} KG", f"{current_l:,.0f} L")
            st.caption(f"Max Limit: {conf['limit']:,} KG")
            st.divider()

    # 3. ส่วนบันทึก รับเข้า/เบิกออก (Admin Only)
    if is_admin:
        st.subheader("📝 บันทึกรายการ (Transaction)")
        with st.form("chem_form"):
            c1, c2, c3 = st.columns(3)
            with c1: 
                chem_select = st.selectbox("เลือกสารเคมี:", list(CHEMICAL_CONFIG.keys()))
                action = st.selectbox("ทำรายการ:", ["📥 เติมสารเคมี (In)", "📤 เบิกจ่าย (Out)"])
            with c2:
                kg_input = st.number_input("ปริมาณ (KG):", min_value=0.1, step=10.0)
                # Auto Calculate L for preview
                density_now = CHEMICAL_CONFIG[chem_select]['density']
                st.info(f"≈ {kg_input / density_now:,.2f} Liters (Density: {density_now})")
            with c3:
                date_input = st.date_input("วันที่:", get_thai_now())
                remark = st.text_input("หมายเหตุ/เลขที่เอกสาร:")
            
            submitted = st.form_submit_button("บันทึกข้อมูล", type="primary")
            
            if submitted:
                # Validation เช็คถังเต็ม
                if action == "📥 เติมสารเคมี (In)":
                    current = chem_bal.get(chem_select, 0)
                    if current + kg_input > CHEMICAL_CONFIG[chem_select]['limit']:
                        st.warning(f"⚠️ คำเตือน: การเติมครั้งนี้จะทำให้เกินขีดจำกัด ({CHEMICAL_CONFIG[chem_select]['limit']:,} KG)")
                    save_chem_transaction(date_input, chem_select, "In", kg_input, density_now, remark)
                else:
                    # Validation เช็คของไม่พอจ่าย
                    current = chem_bal.get(chem_select, 0)
                    if current - kg_input < 0:
                        st.error("❌ ทำรายการไม่ได้: ปริมาณคงเหลือไม่พอจ่าย")
                    else:
                        save_chem_transaction(date_input, chem_select, "Out", kg_input, density_now, remark)

    # 4. ตารางประวัติ (History Table)
    st.subheader("📜 ประวัติการทำรายการ")
    if not chem_df.empty:
        # ปุ่มดาวน์โหลด
        if is_admin:
            csv = chem_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลดประวัติสารเคมี (CSV)", csv, "chemical_history.csv", "text/csv")
        
        st.dataframe(
            chem_df[['date', 'chem_code', 'action_type', 'qty_kg', 'qty_l', 'remark']],
            use_container_width=True, hide_index=True,
            column_config={
                "qty_kg": st.column_config.NumberColumn("ปริมาณ (KG)", format="%.2f"),
                "qty_l": st.column_config.NumberColumn("ปริมาณ (L)", format="%.2f"),
                "date": st.column_config.DateColumn("วันที่"),
                "action_type": "รายการ"
            }
        )
    else:
        st.info("ยังไม่มีประวัติรายการ")


# --- (เมนูเดิม: Dashboard) ---
elif choice == "📊 Dashboard & แจ้งเตือน" and is_admin:
    st.header("📊 Dashboard ภาพรวมสต็อก")
    if not balance_df.empty:
        st.subheader("⚠️ แจ้งเตือนวันหมดอายุ")
        today = get_thai_now().strftime('%Y-%m-%d')
        next_30 = (get_thai_now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        has_exp = balance_df[balance_df['expiry_date'].notna() & (balance_df['Balance']>0)]
        expired = has_exp[has_exp['expiry_date'] < today]
        near = has_exp[(has_exp['expiry_date'] >= today) & (has_exp['expiry_date'] <= next_30)]
        
        c1, c2 = st.columns(2)
        with c1:
            if not expired.empty: 
                st.error(f"⛔ หมดอายุแล้ว ({len(expired)} รายการ)")
                st.dataframe(expired[['expiry_date','item_name','Balance']], hide_index=True)
            else: st.success("✅ ไม่มีของหมดอายุ")
        with c2:
            if not near.empty: 
                st.warning(f"⚠️ ใกล้หมดอายุ ({len(near)} รายการ)")
                st.dataframe(near[['expiry_date','item_name','Balance']], hide_index=True)
            else: st.success("✅ ไม่มีของใกล้หมดอายุ")
            
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("📦 รายการทั้งหมด", len(balance_df))
        c2.metric("⚠️ สินค้าหมด", len(balance_df[balance_df['Balance']<=0]))
        c3.metric("📅 อัปเดต (เวลาไทย)", get_thai_now().strftime("%H:%M:%S"))
    else: st.info("ยังไม่มีข้อมูล")

# --- (เมนูเดิม: วัสดุทั้งหมด) ---
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
        else: st.caption("ℹ️ เฉพาะ Material Control Department เท่านั้นที่สามารถดาวน์โหลดข้อมูลได้")
        
        st.dataframe(show[['item_code','item_name','category','In','Out','Balance','unit','expiry_date']], use_container_width=True, hide_index=True)
    else: st.info("ไม่มีข้อมูล")

# --- (เมนูเดิม: วัสดุหมดสต๊อก) ---
elif choice == "📉 วัสดุหมดสต๊อก (Out of Stock)":
    st.header("📉 รายงานวัสดุที่ถูกเบิกจ่ายหมดแล้ว (Balance ≤ 0)")
    if not balance_df.empty:
        out_of_stock_df = balance_df[balance_df['Balance'] <= 0].copy()
        if not out_of_stock_df.empty:
            c1, c2 = st.columns([2,1])
            with c1: txt = st.text_input("🔍 ค้นหา:", placeholder="ชื่อ...")
            with c2: 
                cats = ["ทั้งหมด"] + sorted([c for c in out_of_stock_df['category'].unique() if c!='-'])
                sel = st.selectbox("หมวดหมู่:", cats)
            show = out_of_stock_df
            if sel != "ทั้งหมด": show = show[show['category']==sel]
            if txt: show = show[show.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)]

            if is_admin:
                csv = show.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 ดาวน์โหลด (CSV)", csv, "out_of_stock.csv", "text/csv", type="primary")
            
            st.error(f"พบรายการหมดจำนวน: {len(show)} รายการ")
            st.dataframe(show[['item_code','item_name','category','Balance','unit']], use_container_width=True, hide_index=True)
        else: st.success("✅ เยี่ยมมาก! ไม่มีรายการวัสดุหมดสต๊อกในขณะนี้")
    else: st.info("ไม่มีข้อมูล")

# --- (เมนูเดิม: ค้นหา) ---
elif choice == "🔍 ค้นหา (Search)":
    st.header("🔍 ค้นหาประวัติรายตัว")
    if not df.empty:
        txt = st.text_input("พิมพ์รหัส/ชื่อ:", key="search")
        if txt:
            res = df[df.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)]
            if not res.empty:
                if is_admin:
                    in_sum = res[res['action_type']=='In']['quantity'].sum()
                    out_sum = res[res['action_type']=='Out']['quantity'].sum()
                    st.markdown(f"**สรุป:** รับ {in_sum:,.2f} | จ่าย {out_sum:,.2f} | คงเหลือ {in_sum-out_sum:,.2f}")
                    st.dataframe(res[['date','action_type','item_name','quantity','department','requester','remark']], use_container_width=True, hide_index=True)
                else:
                    summary = calculate_inventory(res)
                    for i, r in summary.iterrows():
                         with st.container():
                            c1,c2,c3,c4 = st.columns([2,1,1,1])
                            c1.markdown(f"**{r['item_name']}**\nCode: {r['item_code']}")
                            c2.metric("รับ", f"{r['In']:,.2f}")
                            c3.metric("จ่าย", f"{r['Out']:,.2f}")
                            c4.metric("คงเหลือ", f"{r['Balance']:,.2f}", delta_color="off" if r['Balance']>0 else "inverse")
                            st.divider()
            else: st.warning("ไม่พบข้อมูล")
    else: st.info("ไม่มีข้อมูล")

# --- (เมนูเดิม: รายงานประจำวัน) ---
elif choice == "📅 รายงานประจำวัน (Daily)" and is_admin:
    st.header("📅 รายงานประจำวัน")
    if not df.empty:
        enriched_df = enrich_transactions(df.copy())
        mode = st.radio("โหมด:", ["รายวัน", "ทั้งหมด"], horizontal=True)
        show_df = enriched_df.copy()
        if mode == "รายวัน":
            date = st.date_input("เลือกวันที่:", get_thai_now()).strftime('%Y-%m-%d')
            show_df = show_df[show_df['date'] == date]
        if not show_df.empty:
            csv = show_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลด (CSV)", csv, "daily_report.csv", "text/csv")
            t1, t2 = st.tabs(["📥 รับเข้า", "📤 เบิกออก"])
            with t1: st.dataframe(show_df[show_df['action_type']=='In'][['date','item_code','item_name','quantity','unit','category','expiry_date','remark']], use_container_width=True, hide_index=True)
            with t2: st.dataframe(show_df[show_df['action_type']=='Out'][['date','item_code','item_name','quantity','unit','category','department','requester','remark']], use_container_width=True, hide_index=True)
        else: st.warning("ไม่มีรายการ")

# --- (เมนูเดิม: รับเข้า/เบิกออก/จัดการ) ---
elif choice == "📥 รับเข้า (In)" and is_admin:
    st.header("📥 รับวัสดุเข้า")
    f = st.file_uploader("Upload Excel (In)", type=['xlsx'], key='in')
    if f:
        d = pd.read_excel(f)
        if st.button("บันทึก"):
            cmap = {'วันที่รับเข้า':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                    'จำนวน':'quantity', 'หน่วย':'unit', 'วันที่หมดอายุ':'expiry_date', 
                    'ประเภทวัสดุ':'category', 'หมายเหตุ':'remark'}
            d = d.rename(columns=cmap)
            req = ['date','item_code','item_name','quantity','unit','expiry_date','category','remark']
            for c in req: 
                if c not in d.columns: d[c] = None
            save_to_db(d[req], 'In')

elif choice == "📤 เบิกออก (Out)" and is_admin:
    st.header("📤 เบิกวัสดุออก")
    f = st.file_uploader("Upload Excel (Out)", type=['xlsx'], key='out')
    if f:
        d = pd.read_excel(f)
        if st.button("บันทึก"):
            cmap = {'วันที่เบิกจ่าย':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                    'จำนวนที่เบิก':'quantity', 'หน่วย':'unit', 'หน่วยงานที่เบิก':'department', 
                    'ผู้ที่ทำการเบิก':'requester', 'หมายเหตุ':'remark'}
            d = d.rename(columns=cmap)
            req = ['date','item_code','item_name','quantity','unit','department','requester','remark']
            for c in req: 
                if c not in d.columns: d[c] = None
            save_to_db(d[req], 'Out')

elif choice == "🔧 จัดการข้อมูล" and is_admin:
    st.header("🔧 จัดการข้อมูล (วัสดุทั่วไป)")
    if not df.empty:
        t1, t2 = st.tabs(["Undo รอบ", "ลบรายบรรทัด"])
        with t1:
            times = df['upload_time'].unique() if 'upload_time' in df.columns else []
            sel = st.selectbox("เลือกรอบ:", times)
            if st.button("ลบทั้งรอบนี้"): delete_batch(sel); st.rerun()
        with t2:
            st.dataframe(df)
            ids = st.multiselect("เลือก ID:", df['id'])
            if st.button("ลบที่เลือก"): delete_data(ids); st.rerun()