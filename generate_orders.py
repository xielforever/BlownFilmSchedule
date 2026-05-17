import random
import datetime
import openpyxl

def generate_orders():
    file_path = 'input/吹膜机排程数据.xlsx'
    wb = openpyxl.load_workbook(file_path)
    sheet = wb.worksheets[1]  # 订单表
    
    # 彻底清理之前追加的订单 (假设原版只有32个订单，大概到第34行)
    # 找到第一个新生成的订单号 ORD-033
    start_del_row = None
    for row in range(2, sheet.max_row + 1):
        val = sheet.cell(row=row, column=1).value
        if val == 'ORD-033':
            start_del_row = row
            break
            
    if start_del_row:
        sheet.delete_rows(start_del_row, sheet.max_row - start_del_row + 1)
        
    start_id = 33
    
    product_types = [
        '医用多层输液袋膜', '医药袋高洁净内衬膜', '医药袋常规内衬膜', 
        '医疗器械顶盖透气膜', '医疗器械吸塑包装膜', '医用大宗防潮外包装膜', '临床试验加急样品膜'
    ]
    
    cleanrooms = ['Class_10K', 'Class_100K', 'NO']
    customer_classes = ['VIP', 'STANDARD']
    
    base_date = datetime.datetime(2026, 5, 17, 8, 0)
    
    for i in range(200):
        o_id = f"ORD-{start_id + i:03d}"
        
        is_extreme = random.random() < 0.15
        
        ptype = random.choice(product_types)
        
        # 为了保证不超物力边界，控制在合理区间
        width = random.randint(800, 1500)
        thickness = random.randint(50, 100)
        
        if is_extreme:
            qty = random.choice([500, 60000, 100000]) # 极少或极大
        else:
            qty = random.randint(2000, 15000)
            
        cleanroom = 'Class_10K' if ptype in ['医用多层输液袋膜', '医药袋高洁净内衬膜'] else random.choice(cleanrooms)
        
        if ptype == '临床试验加急样品膜':
            oclass = 'SAMPLE'
        else:
            oclass = random.choices(['NORMAL', 'URGENT'], weights=[0.8, 0.2])[0]
            
        cclass = 'VIP' if oclass == 'URGENT' or random.random() < 0.2 else 'STANDARD'
        
        order_date = base_date - datetime.timedelta(days=random.randint(1, 5), hours=random.randint(0, 23))
        
        # 极端交期：紧急插单
        if is_extreme and oclass == 'URGENT':
            due_date = base_date + datetime.timedelta(hours=random.randint(24, 48))
        else:
            due_date = base_date + datetime.timedelta(days=random.randint(3, 20), hours=random.randint(0, 23))
            
        corona = random.choice(['YES', 'NO'])
        core = random.choice([3, 6])
        
        mat_avail = 0
        if random.random() < 0.2:
            # 极端等料：要等1-3天才到货
            mat_avail = random.randint(1440, 4320)
            
        row_data = [
            o_id, ptype, width, thickness, qty, cleanroom, 
            order_date.strftime("%Y-%m-%d %H:%M"),
            due_date.strftime("%Y-%m-%d %H:%M"),
            cclass, oclass, corona, core, mat_avail
        ]
        
        sheet.append(row_data)
        
    wb.save(file_path)
    print(f"成功清理并重新生成追加 200 个订单到 {file_path}")

if __name__ == '__main__':
    generate_orders()
