import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion import BlownFilmDataIngestionPipeline
from src.config import INPUT_EXCEL_PATH

def check_feasibility():
    pipeline = BlownFilmDataIngestionPipeline()
    machines, orders, recipes_map, setup_mgr = pipeline.load_from_excel(INPUT_EXCEL_PATH)
    
    infeasible_count = 0
    for o in orders:
        eligible = []
        for m in machines:
            if m.can_produce(o):
                eligible.append(m.machine_id)
        if not eligible:
            print(f"Order {o.order_id} (Product: {o.product_type}, Width: {o.target_width}, Thickness: {o.target_thickness}, Cleanroom: {o.cleanroom_req}) has NO eligible machine.")
            infeasible_count += 1
            
    print(f"Total infeasible orders: {infeasible_count}")

if __name__ == "__main__":
    check_feasibility()
