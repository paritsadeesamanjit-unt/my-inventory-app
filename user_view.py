import streamlit as st
import pandas as pd
import sqlite3
import time

# --- ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="ตรวจสอบวัสดุ (Viewer)", layout="wide")

# ==========================================
# 1. ฟังก์ชันโหลดและคำนวณ (เหมือนไฟล์ Admin)
# ==========================================
DB_NAME = 'inventory_final.db'

def load_data():
    """โหลดข้อมูลแบบ Real-time (ไม่ใช้ Cache)"""
    try:
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
        conn.close()
        return df
    except Exception as e:
        return pd.DataFrame()

def calculate_inventory(df):
    """คำนวณยอดคงเหลือ + ดึง Category/Expiry ให้ครบถ้วน"""
    if df.empty:
        return pd.DataFrame()
    
    # แปลง Type เพื่อป้องกัน Error เวลา Merge
    df['item_code'] = df['item_code'].astype(str)
    df['item_name'] = df['item_name'].astype(str)

    # 1. Group ยอด (In - Out)
    balance_df = df.pivot_table(
        index=['item_code', 'item_name'], 
        columns='action_type', 
        values='quantity', 
        aggfunc='sum', 
        fill_value=0
    ).reset_index()
    
    # 2. หา Unit ล่าสุด
    latest_unit = df.sort_values('date', ascending=False).drop_duplicates(subset=['item_code', 'item_name'])
    
    # 3. หา Category ที่ถูกต้อง (กรองเอาเฉพาะที่มีค่า)
    valid_cats = df[(df['category'].notna()) & (df['category'] != '') & (df['category'] != '-') & (df['category'] != 'None')]
    if not valid_cats.empty:
        best_category = valid_cats.sort_values('date', ascending=False).drop_duplicates(subset=['item_code', 'item_name'])[['item_code', 'item_name', 'category']]
    else:
        best_category = pd.DataFrame(columns=['item_code', 'item_name', 'category'])

    # 4. หาวันหมดอายุ (เร็วที่สุด)
    valid_expiry = df[(df['action_type'] == 'In') & (df['expiry_date'].notna()) & (df['expiry_date'] != '')]
    if not valid_expiry.empty:
        earliest_expiry = valid_expiry.groupby(['item_code', 'item_name'])['expiry_date'].min().reset_index()
    else:
        earliest_expiry = pd.DataFrame(columns=['item_code', 'item_name', 'expiry_date'])

    # 5. Merge รวมร่าง
    balance_df = pd.merge(balance_df, latest_unit[['item_code', 'item_name', 'unit']], on=['item_code', 'item_name'], how='left')
    balance_df = pd.merge(balance_df, best_category, on=['item_code', 'item_name'], how='left')
    balance_df = pd.merge(balance_df, earliest_expiry, on=['item_code', 'item_name'], how='left')

    # จัดการค่าว่าง
    balance_df['category'] = balance_df['category'].fillna('-')
    balance_df['unit'] = balance_df['unit'].fillna('')

    if 'In' not in balance_df.columns: balance_df['In'] = 0.0
    if 'Out' not in balance_df.columns: balance_df['Out'] = 0.0
    balance_df['Balance'] = balance_df['In'] - balance_df['Out']
    
    return balance_df

# ==========================================
# 2. ส่วนหน้าจอเว็บไซต์ (User UI)
# ==========================================
st.title("📦 ระบบตรวจสอบวัสดุคงคลัง (สำหรับหน่วยงาน)")
st.caption("ข้อมูลล่าสุด (Real-time View)")

# Sidebar
st.sidebar.header("เมนูใช้งาน")
menu = ["🔍 ค้นหาวัสดุ (Search)", "📋 รายการวัสดุคงเหลือทั้งหมด"]
choice = st.sidebar.radio("เลือกเมนู:", menu)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 กดเพื่ออัปเดตข้อมูลล่าสุด"):
    st.rerun()
st.sidebar.caption(f"ข้อมูล ณ เวลา: {time.strftime('%H:%M:%S')}")

# โหลดข้อมูล
df = load_data()
if not df.empty:
    view_df = calculate_inventory(df)
else:
    view_df = pd.DataFrame()

# --- หน้า 1: ค้นหา ---
if choice == "🔍 ค้นหาวัสดุ (Search)":
    st.subheader("🔍 ค้นหาและตรวจสอบยอด")
    
    if not view_df.empty:
        txt = st.text_input("พิมพ์รหัส หรือ ชื่อวัสดุ:", placeholder="ค้นหา...")
        
        if txt:
            # ค้นหาแบบยืดหยุ่น (Case Insensitive)
            mask = view_df.astype(str).apply(lambda x: x.str.contains(txt, case=False, na=False)).any(axis=1)
            res = view_df[mask]
            
            if not res.empty:
                st.info(f"พบ {len(res)} รายการ")
                for i, r in res.iterrows():
                    with st.container():
                        c1, c2, c3, c4 = st.columns([2.5, 1, 1, 1.2])
                        with c1:
                            st.markdown(f"**{r['item_name']}**")
                            # แสดง Category และ Exp
                            exp_txt = f" | Exp: {r['expiry_date']}" if pd.notna(r['expiry_date']) else ""
                            st.caption(f"Code: {r['item_code']} | Type: {r['category']}{exp_txt}")
                        with c2:
                            st.metric("รับเข้า", f"{r['In']:,.2f}")
                        with c3:
                            st.metric("เบิกออก", f"{r['Out']:,.2f}")
                        with c4:
                            st.metric("คงเหลือ", f"{r['Balance']:,.2f} {r['unit']}", 
                                      delta_color="off" if r['Balance']>0 else "inverse")
                        st.divider()
            else: st.warning("ไม่พบข้อมูล")
    else: st.warning("ไม่พบฐานข้อมูล หรือฐานข้อมูลว่างเปล่า")

# --- หน้า 2: ดูทั้งหมด ---
elif choice == "📋 รายการวัสดุคงเหลือทั้งหมด":
    st.subheader("📋 สรุปยอดวัสดุทั้งหมดในคลัง")
    if not view_df.empty:
        # ตัวกรอง
        cats = sorted([c for c in view_df['category'].unique() if c != '-'])
        all_cats = ["ทั้งหมด"] + cats
        sel = st.selectbox("กรองตามหมวดหมู่:", all_cats)
        
        show = view_df.copy()
        if sel != "ทั้งหมด": show = show[show['category'] == sel]
        
        # ปุ่ม Download CSV
        csv = show.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 ดาวน์โหลดตารางนี้ (Excel/CSV)", csv, "stock_view.csv", "text/csv")
        
        # แสดงตาราง
        st.dataframe(
            show[['item_code','item_name','category','In','Out','Balance','unit','expiry_date']], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "item_code": "รหัส", "item_name": "ชื่อรายการ", "category": "หมวดหมู่",
                "In": st.column_config.NumberColumn("รับเข้า", format="%.2f"),
                "Out": st.column_config.NumberColumn("จ่ายออก", format="%.2f"),
                "Balance": st.column_config.NumberColumn("คงเหลือ", format="%.2f"),
                "unit": "หน่วย",
                "expiry_date": st.column_config.DateColumn("วันหมดอายุ", format="DD/MM/YYYY")
            }
        )
    else: st.info("ไม่มีข้อมูล")

# ซ่อนเมนูขีดสามขีดของ Streamlit เพื่อความสวยงาม
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)