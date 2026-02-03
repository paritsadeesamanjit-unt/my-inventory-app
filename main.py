import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta
import time

# ==========================================
# 1. ตั้งค่าและจัดการฐานข้อมูล (Shared DB)
# ==========================================
st.set_page_config(page_title="Inventory System (Combined)", layout="wide")

# ใช้ Absolute Path เพื่อความชัวร์
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'inventory_final.db')

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
        batch_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        df['upload_time'] = batch_timestamp
        
        for col in ['date', 'expiry_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
        if 'item_code' in df.columns:
            df['item_code'] = df['item_code'].fillna('-')

        df.to_sql('transactions', conn, if_exists='append', index=False)
        st.success(f"✅ บันทึกข้อมูล '{action_type}' เรียบร้อย! (Batch: {batch_timestamp})")
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
# 2. ส่วนหน้าจอหลัก (Main Interface)
# ==========================================
init_db()

# Sidebar เลือกโหมด
st.sidebar.title("📌 เลือกโหมดการใช้งาน")
app_mode = st.sidebar.radio("Go to:", ["👀 User View (ดูข้อมูล)", "⚙️ Admin (จัดการข้อมูล)"])

# ------------------------------------------
# โหมด ADMIN (จัดการข้อมูล)
# ------------------------------------------
if app_mode == "⚙️ Admin (จัดการข้อมูล)":
    st.title("⚙️ Admin Panel: จัดการสต๊อก")
    
    # ใส่รหัสผ่านง่ายๆ กันคนกดผิด (แก้รหัสตรงนี้ได้เลย)
    password = st.sidebar.text_input("🔑 ใส่รหัสผ่าน Admin", type="password")
    
    if password == "1111100000":  # <--- ตั้งรหัสผ่านตรงนี้
        menu = ["📥 รับเข้า (In)", "📤 เบิกออก (Out)", "🔧 ลบ/แก้ไข"]
        choice = st.radio("เมนู Admin:", menu, horizontal=True)
        st.divider()
        
        if choice == "📥 รับเข้า (In)":
            f = st.file_uploader("Upload Excel (In)", type=['xlsx'], key='in')
            if f:
                d = pd.read_excel(f)
                if st.button("บันทึกรับเข้า"):
                    cmap = {'วันที่รับเข้า':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                            'จำนวน':'quantity', 'หน่วย':'unit', 'วันที่หมดอายุ':'expiry_date', 
                            'ประเภทวัสดุ':'category', 'หมายเหตุ':'remark'}
                    d = d.rename(columns=cmap)
                    req = ['date','item_code','item_name','quantity','unit','expiry_date','category','remark']
                    for c in req: 
                        if c not in d.columns: d[c] = None
                    save_to_db(d[req], 'In')
                    
        elif choice == "📤 เบิกออก (Out)":
            f = st.file_uploader("Upload Excel (Out)", type=['xlsx'], key='out')
            if f:
                d = pd.read_excel(f)
                if st.button("บันทึกเบิกออก"):
                    cmap = {'วันที่เบิกจ่าย':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                            'จำนวนที่เบิก':'quantity', 'หน่วย':'unit', 'หน่วยงานที่เบิก':'department', 
                            'ผู้ที่ทำการเบิก':'requester', 'หมายเหตุ':'remark'}
                    d = d.rename(columns=cmap)
                    req = ['date','item_code','item_name','quantity','unit','department','requester','remark']
                    for c in req: 
                        if c not in d.columns: d[c] = None
                    save_to_db(d[req], 'Out')
                    
        elif choice == "🔧 ลบ/แก้ไข":
            df = load_data()
            if not df.empty:
                t1, t2 = st.tabs(["Undo รอบอัปโหลด", "ลบรายบรรทัด"])
                with t1:
                    times = df['upload_time'].unique() if 'upload_time' in df else []
                    sel = st.selectbox("เลือกรอบเวลา:", times)
                    if st.button("ลบทั้งรอบ"): delete_batch(sel); st.rerun()
                with t2:
                    st.dataframe(df)
                    ids = st.multiselect("เลือก ID:", df['id'])
                    if st.button("ลบที่เลือก"): delete_data(ids); st.rerun()
    elif password:
        st.error("รหัสผ่านผิดครับ")
    else:
        st.info("กรุณาใส่รหัสผ่านที่ Sidebar ด้านซ้าย (รหัส: 1234)")

# ------------------------------------------
# โหมด USER (ดูข้อมูล)
# ------------------------------------------
elif app_mode == "👀 User View (ดูข้อมูล)":
    st.title("📦 ตรวจสอบวัสดุคงคลัง")
    
    # ปุ่ม Refresh ข้อมูล
    if st.button("🔄 รีเฟรชข้อมูลล่าสุด"):
        st.cache_data.clear()
        st.rerun()
        
    df = load_data()
    
    if not df.empty:
        view_df = calculate_inventory(df)
        
        # Dashboard สรุป
        c1, c2, c3 = st.columns(3)
        c1.metric("📦 รายการทั้งหมด", len(view_df))
        c2.metric("⚠️ สินค้าหมด", len(view_df[view_df['Balance']<=0]))
        c3.metric("📅 ข้อมูลล่าสุด", datetime.now().strftime("%H:%M"))
        st.divider()

        # ส่วนค้นหา
        col_search, col_cat = st.columns([2,1])
        with col_search:
            txt = st.text_input("🔍 ค้นหา (รหัส/ชื่อ):")
        with col_cat:
            cats = ["ทั้งหมด"] + sorted([c for c in view_df['category'].unique() if c!='-'])
            sel_cat = st.selectbox("หมวดหมู่:", cats)
            
        # กรองข้อมูล
        show = view_df.copy()
        if sel_cat != "ทั้งหมด": show = show[show['category']==sel_cat]
        if txt: show = show[show.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)]
        
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
    else:
        st.warning("⚠️ ยังไม่มีข้อมูลในระบบ")
        st.info("👈 กรุณาไปที่เมนู 'Admin' เพื่ออัปโหลดไฟล์ Excel ก่อนครับ")