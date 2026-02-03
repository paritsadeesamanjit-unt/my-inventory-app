import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta, timezone
import time

# ==========================================
# 1. ตั้งค่าระบบและฐานข้อมูล
# ==========================================
st.set_page_config(page_title="Inventory System", layout="wide")

# ใช้ Absolute Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'inventory_final.db')

# 🔥 ฟังก์ชันสำหรับดึงเวลาไทย (UTC+7) เสมอ
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
    conn.commit()
    conn.close()

def save_to_db(df, action_type):
    conn = sqlite3.connect(DB_NAME)
    try:
        df['action_type'] = action_type
        # 🔥 ใช้เวลาไทยในการบันทึก Timestamp
        batch_timestamp = get_thai_now().strftime('%Y-%m-%d %H:%M:%S')
        df['upload_time'] = batch_timestamp
        
        for col in ['date', 'expiry_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
        if 'item_code' in df.columns:
            df['item_code'] = df['item_code'].fillna('-')

        df.to_sql('transactions', conn, if_exists='append', index=False)
        st.success(f"✅ บันทึกข้อมูล '{action_type}' เรียบร้อย! (เวลา: {batch_timestamp})")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error: {e}")
    finally:
        conn.close()

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
    ref_df = df[df['category'].notna() & (df['category'] != '') & (df['category'] != '-')]
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
    if not cats.empty:
        best_cat = cats.sort_values('date',ascending=False).drop_duplicates(['item_code','item_name'])[['item_code','item_name','category']]
    else: best_cat = pd.DataFrame(columns=['item_code','item_name','category'])

    exps = df[(df['action_type']=='In') & df['expiry_date'].notna()]
    if not exps.empty:
        min_exp = exps.groupby(['item_code','item_name'])['expiry_date'].min().reset_index()
    else: min_exp = pd.DataFrame(columns=['item_code','item_name','expiry_date'])

    bal = bal.merge(latest[['item_code','item_name','unit']], on=['item_code','item_name'], how='left')
    bal = bal.merge(best_cat, on=['item_code','item_name'], how='left')
    bal = bal.merge(min_exp, on=['item_code','item_name'], how='left')

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
    st.success("ลบข้อมูลสำเร็จ")
    st.cache_data.clear()

def delete_batch(batch):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM transactions WHERE upload_time = ?", (batch,))
    conn.commit()
    conn.close()
    st.success(f"ลบรอบ {batch} สำเร็จ")
    st.cache_data.clear()

# ==========================================
# 2. ส่วน User Interface (UI)
# ==========================================
init_db()

# --- Sidebar ---
st.sidebar.title("🔐 เข้าสู่ระบบ")
role = st.sidebar.radio("เลือกสิทธิ์การใช้งาน:", ["👤 User (ทั่วไป)", "🔑 Admin (ผู้ดูแล)"])

is_admin = False
if role == "🔑 Admin (ผู้ดูแล)":
    st.sidebar.markdown("---")
    password = st.sidebar.text_input("รหัสผ่าน Admin:", type="password")
    if password == "1111100000":
        is_admin = True
        st.sidebar.success("ล็อกอินสำเร็จ! ✅")
    elif password:
        st.sidebar.error("รหัสผิด ❌")

if is_admin:
    menu_options = [
        "📊 Dashboard & แจ้งเตือน", 
        "📋 วัสดุทั้งหมด (Overview)",
        "🔍 ค้นหา (Search)",   
        "📅 รายงานประจำวัน (Daily)", 
        "📥 รับเข้า (In)", 
        "📤 เบิกออก (Out)", 
        "🔧 จัดการข้อมูล"
    ]
else:
    menu_options = ["📋 วัสดุทั้งหมด (Overview)", "🔍 ค้นหา (Search)"]

st.sidebar.markdown("---")
choice = st.sidebar.radio("เมนู:", menu_options)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 รีเฟรชข้อมูล"): st.rerun()

# โหลดข้อมูล
df = load_data()
if not df.empty:
    balance_df = calculate_inventory(df)
else:
    balance_df = pd.DataFrame()

# ==========================================
# 3. ส่วนแสดงผลเนื้อหา (Content)
# ==========================================

# --- 1. Dashboard (Admin Only) ---
if choice == "📊 Dashboard & แจ้งเตือน" and is_admin:
    st.header("📊 Dashboard ภาพรวมสต็อก")
    if not balance_df.empty:
        st.subheader("⚠️ แจ้งเตือนวันหมดอายุ")
        
        # 🔥 ใช้เวลาไทยในการเปรียบเทียบวันหมดอายุ
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
        # 🔥 แสดงเวลาไทย
        c3.metric("📅 อัปเดต (เวลาไทย)", get_thai_now().strftime("%H:%M:%S"))
    else:
        st.info("ยังไม่มีข้อมูล กรุณาไปเมนู 'รับเข้า' เพื่ออัปโหลดไฟล์")

# --- 2. วัสดุทั้งหมด (Admin + User) ---
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
        
        csv = show.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลด (CSV)", csv, "stock_overview.csv", "text/csv")
        
        st.dataframe(
            show[['item_code','item_name','category','In','Out','Balance','unit','expiry_date']],
            use_container_width=True, hide_index=True,
            column_config={
                "In": st.column_config.NumberColumn("รับ", format="%.2f"),
                "Out": st.column_config.NumberColumn("จ่าย", format="%.2f"),
                "Balance": st.column_config.NumberColumn("คงเหลือ", format="%.2f"),
                "expiry_date": st.column_config.DateColumn("วันหมดอายุ", format="DD/MM/YYYY")
            }
        )
    else: st.info("ไม่มีข้อมูล")

# --- 3. ค้นหา (Admin + User) ---
elif choice == "🔍 ค้นหา (Search)":
    st.header("🔍 ค้นหาประวัติรายตัว")
    if not df.empty:
        txt = st.text_input("พิมพ์รหัส/ชื่อ:")
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
                            c1, c2, c3, c4 = st.columns([2,1,1,1])
                            c1.markdown(f"**{r['item_name']}**\nCode: {r['item_code']}")
                            c2.metric("รับ", f"{r['In']:,.2f}")
                            c3.metric("จ่าย", f"{r['Out']:,.2f}")
                            c4.metric("คงเหลือ", f"{r['Balance']:,.2f}", delta_color="off" if r['Balance']>0 else "inverse")
                            st.divider()
            else: st.warning("ไม่พบข้อมูล")
    else: st.info("ไม่มีข้อมูล")

# --- 4. รายงานประจำวัน (Daily) ---
elif choice == "📅 รายงานประจำวัน (Daily)" and is_admin:
    st.header("📅 รายงานประจำวัน")
    if not df.empty:
        enriched_df = enrich_transactions(df.copy())
        
        mode = st.radio("โหมด:", ["รายวัน", "ทั้งหมด"], horizontal=True)
        show_df = enriched_df.copy()
        
        if mode == "รายวัน":
            # 🔥 ใช้วันที่ปัจจุบันแบบไทย (UTC+7)
            date = st.date_input("เลือกวันที่:", get_thai_now()).strftime('%Y-%m-%d')
            show_df = show_df[show_df['date'] == date]
            
        if not show_df.empty:
            csv = show_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลด (CSV)", csv, "daily_report.csv", "text/csv")
            
            t1, t2 = st.tabs(["📥 รับเข้า (In)", "📤 เบิกออก (Out)"])
            
            cols_in = ['date', 'item_code', 'item_name', 'quantity', 'unit', 'category', 'expiry_date', 'remark']
            cols_out = ['date', 'item_code', 'item_name', 'quantity', 'unit', 'category', 'department', 'requester', 'remark']
            
            with t1: 
                st.dataframe(show_df[show_df['action_type']=='In'][cols_in], use_container_width=True, hide_index=True,
                    column_config={"date": st.column_config.DateColumn("วันที่"), "expiry_date": st.column_config.DateColumn("วันหมดอายุ")})
            with t2: 
                st.dataframe(show_df[show_df['action_type']=='Out'][cols_out], use_container_width=True, hide_index=True,
                    column_config={"date": st.column_config.DateColumn("วันที่")})
        else: st.warning("ไม่มีรายการในช่วงเวลานี้")

# --- 5. รับเข้า (Admin Only) ---
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

# --- 6. เบิกออก (Admin Only) ---
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

# --- 7. จัดการข้อมูล (Admin Only) ---
elif choice == "🔧 จัดการข้อมูล" and is_admin:
    st.header("🔧 จัดการข้อมูล")
    if not df.empty:
        t1, t2 = st.tabs(["Undo (ลบทั้งรอบ)", "ลบรายบรรทัด"])
        with t1:
            times = df['upload_time'].unique() if 'upload_time' in df.columns else []
            sel = st.selectbox("เลือกรอบเวลา (เวลาไทย):", times)
            if st.button("ลบทั้งรอบนี้"): delete_batch(sel); st.rerun()
        with t2:
            st.dataframe(df)
            ids = st.multiselect("เลือก ID ลบ:", df['id'])
            if st.button("ลบที่เลือก"): delete_data(ids); st.rerun()