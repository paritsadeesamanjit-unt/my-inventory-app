import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

# ==========================================
# 1. ส่วนจัดการฐานข้อมูล (Database Management)
# ==========================================
import os

# หาที่อยู่ปัจจุบันของไฟล์โปรแกรม
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# สั่งให้สร้าง DB ในโฟลเดอร์เดียวกันนี้แหละ
DB_NAME = os.path.join(BASE_DIR, 'inventory_final.db')

def init_db():
    """สร้างฐานข้อมูลและตารางเก็บข้อมูลถ้ายังไม่มี"""
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
    """บันทึกข้อมูลจาก DataFrame ลงฐานข้อมูล"""
    conn = sqlite3.connect(DB_NAME)
    try:
        df['action_type'] = action_type
        batch_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        df['upload_time'] = batch_timestamp
        
        # แปลงวันที่ให้เป็นมาตรฐาน YYYY-MM-DD
        for col in ['date', 'expiry_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
        
        # จัดการค่าว่างของรหัสวัสดุ
        if 'item_code' in df.columns:
            df['item_code'] = df['item_code'].fillna('-')

        df.to_sql('transactions', conn, if_exists='append', index=False)
        st.success(f"✅ บันทึกข้อมูล '{action_type}' เรียบร้อย! (Batch ID: {batch_timestamp})")
        st.cache_data.clear() # ล้าง Cache เพื่อให้ข้อมูลอัปเดตทันที
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการบันทึก: {e}")
    finally:
        conn.close()

def load_data():
    """ดึงข้อมูลทั้งหมดจากฐานข้อมูล"""
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY date DESC, id DESC", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def delete_batch(batch_time):
    """ลบข้อมูลตามรอบเวลาอัปโหลด (Undo)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM transactions WHERE upload_time = ?", (batch_time,))
        conn.commit()
        st.success(f"🗑️ ยกเลิกการอัปโหลดรอบ {batch_time} เรียบร้อย")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
    finally:
        conn.close()

def delete_data(ids_to_delete):
    """ลบข้อมูลทีละรายการตาม ID"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        if len(ids_to_delete) == 1:
            c.execute(f"DELETE FROM transactions WHERE id = {ids_to_delete[0]}")
        else:
            c.execute(f"DELETE FROM transactions WHERE id IN {tuple(ids_to_delete)}")
        conn.commit()
        st.success(f"🗑️ ลบข้อมูลเรียบร้อยแล้ว")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
    finally:
        conn.close()

# ==========================================
# 2. ฟังก์ชันคำนวณและประมวลผล (Core Logic)
# ==========================================
def calculate_inventory(df):
    """คำนวณยอดคงเหลือ และดึงข้อมูล Category/Expiry ที่ถูกต้องที่สุด"""
    if df.empty:
        return pd.DataFrame()
    
    # แปลงเป็น String เพื่อการจับคู่ที่แม่นยำ
    df['item_code'] = df['item_code'].astype(str)
    df['item_name'] = df['item_name'].astype(str)
    
    # 1. Group รวมยอด (In - Out)
    balance_df = df.pivot_table(
        index=['item_code', 'item_name'], 
        columns='action_type', 
        values='quantity', 
        aggfunc='sum', 
        fill_value=0
    ).reset_index()
    
    # 2. หา Unit ล่าสุด
    latest_unit = df.sort_values('date', ascending=False).drop_duplicates(subset=['item_code', 'item_name'])
    
    # 3. หา Category ที่ถูกต้อง (ไม่เอาค่าว่าง/ค่าขีด จากรายการเบิกออก)
    valid_cats = df[(df['category'].notna()) & (df['category'] != '') & (df['category'] != '-') & (df['category'] != 'None')]
    if not valid_cats.empty:
        best_category = valid_cats.sort_values('date', ascending=False).drop_duplicates(subset=['item_code', 'item_name'])[['item_code', 'item_name', 'category']]
    else:
        best_category = pd.DataFrame(columns=['item_code', 'item_name', 'category'])

    # 4. หาวันหมดอายุ (เร็วที่สุด) จากรายการรับเข้า (In)
    valid_expiry = df[(df['action_type'] == 'In') & (df['expiry_date'].notna()) & (df['expiry_date'] != '')]
    if not valid_expiry.empty:
        earliest_expiry = valid_expiry.groupby(['item_code', 'item_name'])['expiry_date'].min().reset_index()
    else:
        earliest_expiry = pd.DataFrame(columns=['item_code', 'item_name', 'expiry_date'])

    # 5. รวมข้อมูลทั้งหมดเข้าด้วยกัน
    balance_df = pd.merge(balance_df, latest_unit[['item_code', 'item_name', 'unit']], on=['item_code', 'item_name'], how='left')
    balance_df = pd.merge(balance_df, best_category, on=['item_code', 'item_name'], how='left')
    balance_df = pd.merge(balance_df, earliest_expiry, on=['item_code', 'item_name'], how='left')

    # เติมค่าว่าง
    balance_df['category'] = balance_df['category'].fillna('-')
    balance_df['unit'] = balance_df['unit'].fillna('')

    # คำนวณคงเหลือ
    if 'In' not in balance_df.columns: balance_df['In'] = 0.0
    if 'Out' not in balance_df.columns: balance_df['Out'] = 0.0
    
    balance_df['Balance'] = balance_df['In'] - balance_df['Out']
    
    return balance_df

# ==========================================
# 3. ส่วนหน้าจอเว็บไซต์ (User Interface)
# ==========================================
st.set_page_config(page_title="Stock Manager (Admin)", layout="wide")
init_db()

st.title("📦 ระบบบริหารจัดการวัสดุ (Stock Manager)")

menu = [
    "📊 Dashboard & แจ้งเตือน", 
    "📋 วัสดุทั้งหมด (All Materials)",
    "🔍 ค้นหาวัสดุ (Search)",   
    "📅 รายงานประจำวัน (Daily)", 
    "📥 รับเข้า (In)", 
    "📤 เบิกออก (Out)", 
    "🔧 จัดการข้อมูล"
]
choice = st.sidebar.radio("เมนูใช้งาน", menu)

# --- หน้า 1: Dashboard ---
if choice == "📊 Dashboard & แจ้งเตือน":
    df = load_data()
    if not df.empty:
        balance_df = calculate_inventory(df)
        
        # ส่วนแจ้งเตือนวันหมดอายุ
        st.markdown("### ⚠️ แจ้งเตือนวันหมดอายุ (Expiry Alerts)")
        # หาเฉพาะรายการที่มีวันหมดอายุ
        df_expiry_check = balance_df[balance_df['expiry_date'].notna()].copy()
        
        # กรองเฉพาะที่มีของเหลือ (Balance > 0)
        in_stock_expiry = df_expiry_check[df_expiry_check['Balance'] > 0]
        
        today = datetime.now().strftime('%Y-%m-%d')
        next_30_days = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        # แยกกลุ่ม หมดอายุแล้ว VS ใกล้หมด
        expired = in_stock_expiry[in_stock_expiry['expiry_date'] < today]
        near_expiry = in_stock_expiry[(in_stock_expiry['expiry_date'] >= today) & (in_stock_expiry['expiry_date'] <= next_30_days)]
        
        c1, c2 = st.columns(2)
        with c1:
            if not expired.empty:
                st.error(f"⛔ หมดอายุแล้ว! (ตกค้างในสต๊อก): {len(expired)} รายการ")
                st.dataframe(expired[['expiry_date', 'item_code', 'item_name', 'Balance']], hide_index=True)
            else:
                st.success("✅ ไม่มีวัสดุหมดอายุตกค้าง")
        with c2:
            if not near_expiry.empty:
                st.warning(f"⚠️ กำลังจะหมดอายุ (ใน 30 วัน): {len(near_expiry)} รายการ")
                st.dataframe(near_expiry[['expiry_date', 'item_code', 'item_name', 'Balance']], hide_index=True)
            else:
                st.success("✅ ไม่มีวัสดุใกล้หมดอายุเร็วๆ นี้")
        
        st.markdown("---")
        
        # Card สรุปยอดรวม
        total_items = len(balance_df)
        low_stock = len(balance_df[balance_df['Balance'] <= 0])
        
        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("📦 รายการวัสดุทั้งหมด", f"{total_items} รายการ")
        c_m2.metric("⚠️ สินค้าหมด/ติดลบ", f"{low_stock} รายการ", delta_color="inverse")
        c_m3.metric("📅 อัปเดตล่าสุด", datetime.now().strftime("%H:%M:%S"))

    else:
        st.info("ยังไม่มีข้อมูลในระบบ กรุณานำเข้าไฟล์ Excel")

# --- หน้า 2: วัสดุทั้งหมด ---
elif choice == "📋 วัสดุทั้งหมด (All Materials)":
    st.header("📋 สรุปรายการวัสดุทั้งหมด")
    df = load_data()
    
    if not df.empty:
        balance_df = calculate_inventory(df)
        
        # ตัวกรอง
        c_search, c_filter = st.columns([2, 1])
        with c_search:
            search_txt = st.text_input("🔍 ค้นหา:", placeholder="พิมพ์รหัส หรือ ชื่อวัสดุ...")
        with c_filter:
            cats = ["ทั้งหมด"] + sorted([c for c in balance_df['category'].unique() if c != '-'])
            sel_cat = st.selectbox("หมวดหมู่สินค้า:", cats)
        
        # Logic การกรอง
        df_show = balance_df.copy()
        if sel_cat != "ทั้งหมด":
            df_show = df_show[df_show['category'] == sel_cat]
        if search_txt:
            mask = df_show.astype(str).apply(lambda x: x.str.contains(search_txt, case=False, na=False)).any(axis=1)
            df_show = df_show[mask]
        
        # ปุ่ม Export CSV
        csv = df_show.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 ดาวน์โหลดตารางนี้เป็น Excel (CSV)",
            data=csv,
            file_name='stock_all_materials.csv',
            mime='text/csv',
            type="primary"
        )
        
        st.dataframe(
            df_show[['item_code', 'item_name', 'category', 'In', 'Out', 'Balance', 'unit', 'expiry_date']],
            use_container_width=True, hide_index=True,
            column_config={
                "item_code": "รหัส", "item_name": "ชื่อรายการ", "category": "หมวดหมู่",
                "In": st.column_config.NumberColumn("รับเข้า", format="%.2f"),
                "Out": st.column_config.NumberColumn("จ่ายออก", format="%.2f"),
                "Balance": st.column_config.NumberColumn("คงเหลือ", format="%.2f"),
                "expiry_date": st.column_config.DateColumn("วันหมดอายุ (เร็วสุด)", format="DD/MM/YYYY")
            }
        )
    else:
        st.info("ไม่มีข้อมูล")

# --- หน้า 3: ค้นหาประวัติ ---
elif choice == "🔍 ค้นหาวัสดุ (Search)":
    st.header("🔍 ค้นหาประวัติรายตัว")
    df = load_data()
    if not df.empty:
        search_term = st.text_input("พิมพ์รหัส หรือ ชื่อวัสดุ:", "")
        if search_term:
            mask = df.astype(str).apply(lambda x: x.str.contains(search_term, case=False, na=False)).any(axis=1)
            res = df[mask]
            if not res.empty:
                in_sum = res[res['action_type']=='In']['quantity'].sum()
                out_sum = res[res['action_type']=='Out']['quantity'].sum()
                st.markdown(f"#### 🔢 สรุป: รับ {in_sum:,.2f} | จ่าย {out_sum:,.2f} | คงเหลือ {in_sum-out_sum:,.2f}")
                st.dataframe(res[['date', 'action_type', 'item_name', 'quantity', 'department', 'requester', 'remark']], use_container_width=True, hide_index=True)
            else:
                st.warning("ไม่พบข้อมูล")

# --- หน้า 4: รายงานประจำวัน ---
elif choice == "📅 รายงานประจำวัน (Daily)":
    st.header("🔎 รายงานประจำวัน")
    df = load_data()
    if not df.empty:
        c_mode, c_date = st.columns([1, 2])
        mode = c_mode.radio("โหมด:", ["รายวัน", "ทั้งหมด"])
        
        filter_df = df.copy()
        if mode == "รายวัน":
            s_date = c_date.date_input("เลือกวันที่:", datetime.now()).strftime('%Y-%m-%d')
            filter_df = df[df['date'] == s_date]
            st.caption(f"แสดงข้อมูลวันที่: {s_date}")
            
        if not filter_df.empty:
            # ปุ่ม Export
            csv_report = filter_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 ดาวน์โหลดรายงานนี้ (CSV)", csv_report, "daily_report.csv", "text/csv")
            
            t1, t2 = st.tabs(["📥 รายการรับเข้า", "📤 รายการเบิกออก"])
            with t1:
                st.dataframe(filter_df[filter_df['action_type']=='In'][['date','item_code','item_name','quantity','unit','expiry_date','remark']], use_container_width=True, hide_index=True)
            with t2:
                st.dataframe(filter_df[filter_df['action_type']=='Out'][['date','item_code','item_name','quantity','unit','department','requester']], use_container_width=True, hide_index=True)
        else:
            st.warning("ไม่มีรายการในช่วงเวลานี้")

# --- หน้า 5: รับเข้า ---
elif choice == "📥 รับเข้า (In)":
    st.header("📥 นำเข้าข้อมูล: รับวัสดุ")
    f = st.file_uploader("เลือกไฟล์ Excel (In)", type=['xlsx'], key='in')
    if f:
        d = pd.read_excel(f)
        st.write("ตัวอย่างข้อมูล:", d.head(3))
        if st.button("บันทึกรับเข้า"):
            cmap = {'วันที่รับเข้า':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                    'จำนวน':'quantity', 'หน่วย':'unit', 'วันที่หมดอายุ':'expiry_date', 
                    'ประเภทวัสดุ':'category', 'หมายเหตุ':'remark'}
            d = d.rename(columns=cmap)
            req = ['date','item_code','item_name','quantity','unit','expiry_date','category','remark']
            for c in req: 
                if c not in d.columns: d[c] = None
            save_to_db(d[req], 'In')

# --- หน้า 6: เบิกออก ---
elif choice == "📤 เบิกออก (Out)":
    st.header("📤 นำเข้าข้อมูล: เบิกวัสดุ")
    f = st.file_uploader("เลือกไฟล์ Excel (Out)", type=['xlsx'], key='out')
    if f:
        d = pd.read_excel(f)
        st.write("ตัวอย่างข้อมูล:", d.head(3))
        if st.button("บันทึกเบิกออก"):
            cmap = {'วันที่เบิกจ่าย':'date', 'รหัสวัสดุ':'item_code', 'คำอธิบาย':'item_name', 
                    'จำนวนที่เบิก':'quantity', 'หน่วย':'unit', 'หน่วยงานที่เบิก':'department', 
                    'ผู้ที่ทำการเบิก':'requester', 'หมายเหตุ':'remark'}
            d = d.rename(columns=cmap)
            req = ['date','item_code','item_name','quantity','unit','department','requester','remark']
            for c in req: 
                if c not in d.columns: d[c] = None
            save_to_db(d[req], 'Out')

# --- หน้า 7: จัดการข้อมูล ---
elif choice == "🔧 จัดการข้อมูล":
    st.header("🔧 ลบหรือแก้ไขข้อมูล")
    df = load_data()
    if not df.empty:
        t1, t2 = st.tabs(["ลบตามรอบอัปโหลด (Undo)", "ลบรายบรรทัด"])
        with t1:
            if 'upload_time' in df.columns:
                times = df['upload_time'].unique()
                sel = st.selectbox("เลือกเวลาที่อัปโหลดผิด:", times)
                st.write(df[df['upload_time']==sel].head())
                if st.button("ลบข้อมูลรอบนี้ทั้งหมด", type="primary"):
                    delete_batch(sel)
                    st.rerun()
        with t2:
            st.dataframe(df[['id','date','item_name','quantity','action_type']], use_container_width=True)
            ids = st.multiselect("เลือก ID ที่ต้องการลบ:", df['id'])
            if st.button("ยืนยันลบรายการที่เลือก"):
                delete_data(ids)
                st.rerun()