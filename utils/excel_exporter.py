"""Excel导出器 — 将分析结果和报告导出为Excel文件"""
import os
import sys
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def export_analysis_to_excel(analysis_result: dict, output_path: str):
    """导出学情分析结果为Excel"""
    df = pd.DataFrame(analysis_result["students"])
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="学生分层列表", index=False)

        # 写入分层统计
        stats_df = pd.DataFrame([
            {"分层": tier, "人数": count}
            for tier, count in analysis_result["tier_stats"].items()
        ])
        stats_df.to_excel(writer, sheet_name="分层统计", index=False)

    return output_path


def export_reports_to_excel(reports: list[dict], output_path: str):
    """导出批量报告为Excel（每个学生一个sheet）"""
    wb = Workbook()
    wb.remove(wb.active)

    # 定义样式
    header_font = Font(bold=True, size=14, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    tier_fills = {
        "S": PatternFill(start_color="FF4B4B", end_color="FF4B4B", fill_type="solid"),
        "A": PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid"),
        "B": PatternFill(start_color="4CAF50", end_color="4CAF50", fill_type="solid"),
        "C": PatternFill(start_color="2196F3", end_color="2196F3", fill_type="solid"),
    }
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    for report in reports:
        name = report["学生姓名"]
        tier = report.get("分层", "B")
        # sheet名称限制31字符
        sheet_name = name[:31] if len(name) > 31 else name
        ws = wb.create_sheet(title=sheet_name)

        # 标题行
        ws.merge_cells("A1:B1")
        ws["A1"] = f"{name} - 学情反馈报告"
        ws["A1"].font = header_font
        ws["A1"].fill = header_fill
        ws["A1"].alignment = Alignment(horizontal="center")
        ws.row_dimensions[1].height = 35

        # 分层标签
        ws["A3"] = "分层等级"
        ws["A3"].font = Font(bold=True)
        ws["B3"] = tier
        ws["B3"].fill = tier_fills.get(tier, PatternFill())
        ws["B3"].font = Font(bold=True, color="FFFFFF")

        # 报告内容
        ws["A5"] = "学情报告"
        ws["A5"].font = Font(bold=True)
        ws.merge_cells("A6:B30")
        ws["A6"] = report["学情报告"]
        ws["A6"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[6].height = 300

        # 设置列宽
        ws.column_dimensions["A"].width = 15
        ws.column_dimensions["B"].width = 80

    wb.save(output_path)
    return output_path
