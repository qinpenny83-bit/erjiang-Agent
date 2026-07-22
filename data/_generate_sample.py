"""生成示例学生数据Excel，覆盖S/A/B/C各分层"""
import pandas as pd
import random
import os

random.seed(42)

names = [
    "张伟", "李娜", "王浩", "刘洋", "陈思", "杨帆", "赵敏", "黄磊",
    "周婷", "吴强", "徐佳", "孙鹏", "马丽", "朱俊", "胡雪", "郭明",
    "何静", "林涛", "罗欣", "梁宇"
]
grades = ["初二"] * 10 + ["初三"] * 10
classes = ["数学A班"] * 7 + ["数学B班"] * 7 + ["数学C班"] * 6

data = []
for i in range(20):
    if i < 3:  # S级：高风险
        score_trend = random.choice(["下降", "下降", "平稳"])
        participation = random.choice(["消极", "一般"])
        homework_rate = random.uniform(0.3, 0.6)
        last_contact = random.randint(15, 30)
        renewal_days = random.randint(5, 25)
        renewal_history = random.randint(0, 1)
        parent_attitude = random.choice(["消极", "中性"])
        score = random.randint(40, 65)
    elif i < 8:  # A级：需关注
        score_trend = random.choice(["平稳", "下降"])
        participation = random.choice(["一般", "积极"])
        homework_rate = random.uniform(0.6, 0.8)
        last_contact = random.randint(7, 20)
        renewal_days = random.randint(20, 50)
        renewal_history = random.randint(1, 2)
        parent_attitude = random.choice(["中性", "积极"])
        score = random.randint(60, 80)
    elif i < 15:  # B级：稳定
        score_trend = random.choice(["平稳", "上升"])
        participation = random.choice(["积极", "一般"])
        homework_rate = random.uniform(0.8, 0.95)
        last_contact = random.randint(3, 10)
        renewal_days = random.randint(40, 90)
        renewal_history = random.randint(2, 4)
        parent_attitude = "积极"
        score = random.randint(75, 90)
    else:  # C级：低优先
        score_trend = "上升"
        participation = "积极"
        homework_rate = random.uniform(0.9, 1.0)
        last_contact = random.randint(1, 5)
        renewal_days = random.randint(60, 180)
        renewal_history = random.randint(3, 6)
        parent_attitude = "积极"
        score = random.randint(85, 98)

    data.append({
        "学生姓名": names[i],
        "年级": grades[i],
        "班级": classes[i],
        "最近成绩": score,
        "成绩趋势": score_trend,
        "课堂参与度": participation,
        "作业完成率": f"{round(homework_rate * 100)}%",
        "距上次沟通(天)": last_contact,
        "续费剩余(天)": renewal_days,
        "历史续费次数": renewal_history,
        "家长态度": parent_attitude,
    })

df = pd.DataFrame(data)
output_path = os.path.join(os.path.dirname(__file__), "sample_students.xlsx")
df.to_excel(output_path, index=False)
print(f"示例数据已生成: {output_path}")
print(f"共 {len(df)} 条数据")
print(df[["学生姓名", "最近成绩", "成绩趋势", "课堂参与度", "作业完成率", "续费剩余(天)"]].to_string())
