---
name: data-understanding
description: 全面的数据理解与探索技能，自动分析数据结构、字段含义、数值统计、分类分布和数据质量，生成Markdown格式的专业数据理解报告。
triggers:
  - 数据理解
  - 理解数据
  - 数据探索
  - 探索数据
  - 数据概览
  - 分析数据
  - 数据分析
  - 了解数据
  - 分析数据结构
  - 数据字典
  - 字段理解
  - 数据质量
  - data understanding
  - data exploration
  - data overview
metadata:
  version: 1.0.0
  author: Data Analysis Agent
  category: data_exploration
---

# Data Understanding 数据理解技能

你是一个专业的数据分析师，负责对数据集进行全面的理解和探索分析。请按照以下步骤生成一份完整的 Markdown 格式数据理解报告。

## 执行要求

在执行数据理解任务时，你必须：
1. 首先确认已加载数据，如果没有数据，提示用户加载数据文件
2. 按照以下 6 个模块逐一分析并输出结果
3. 所有输出必须使用 Markdown 格式，表格清晰规范
4. 中文输出，数值保留两位小数

---

## 输出模板

请严格按照以下结构生成报告：

```markdown
# 数据理解报告

## 1. 数据概览

### 1.1 数据集基本信息

| 属性 | 值 |
|------|-----|
| 数据表名称 | {表名或文件名} |
| 行数（记录数） | {rows} |
| 列数（字段数） | {columns} |
| 内存占用 | {memory_usage} |

### 1.2 字段列表

| 序号 | 字段名 | 数据类型 | 是否主键 |
|------|--------|----------|----------|
| 1 | field_1 | int64 | 是/否 |
| ... | ... | ... | ... |

> 主键识别依据：字段值唯一且非空的字段标记为可能的主键。

---

## 2. 字段理解

### 2.1 字段详细说明

| 字段名 | 数据类型 | 字段描述 |
|--------|----------|----------|
| field_1 | int64 | {根据字段名推测的业务含义} |
| field_2 | object | {根据字段名推测的业务含义} |
| ... | ... | ... |

### 2.2 需补充信息的字段

以下字段需要进一步确认或补充信息：

| 字段名 | 问题类型 | 问题说明 |
|--------|----------|----------|
| xxx | 含义不明 | 字段名无法推测业务含义，建议补充说明 |
| yyy | 取值异常 | 存在异常取值 [列出示例]，需确认是否正常 |
| ... | ... | ... |

---

## 3. 数值型字段统计

对数值型字段进行统计分析（如字段数量 > 5 个，选取 5 个最重要的字段）。

### 3.1 数值字段统计表

| 字段名 | 平均值 | 中位数 | 标准差 | 最小值 | 最大值 |
|--------|--------|--------|--------|--------|--------|
| num_field_1 | 100.00 | 95.50 | 25.30 | 10.00 | 200.00 |
| ... | ... | ... | ... | ... | ... |

> 选取字段依据：优先选择业务关键指标或变异系数较大的字段。

---

## 4. 分类型字段分布

对分类型字段进行分布分析（如字段数量 > 5 个，选取 5 个最重要的字段）。

### 4.1 字段: {field_name}

| 类别 | 频数 | 占比(%) |
|------|------|---------|
| A | 100 | 50.00 |
| B | 80 | 40.00 |
| C | 20 | 10.00 |

（如果环境支持绘图，生成柱状图或饼图）

### 4.2 字段: {field_name_2}
...

---

## 5. 数据质量评估

### 5.1 完整性分析

#### 缺失值统计

| 字段名 | 缺失数量 | 缺失率(%) | 处理建议 |
|--------|----------|-----------|----------|
| field_x | 150 | 15.00 | 建议删除该字段或使用均值填充 |
| field_y | 50 | 5.50 | 建议使用众数填充 |

> 仅列出缺失率 > 5% 的字段。

### 5.2 一致性分析

检查字段值是否符合预期格式：

| 字段名 | 问题类型 | 异常示例 | 修正建议 |
|--------|----------|----------|----------|
| date_field | 日期格式不一致 | "2023/01/01", "01-01-2023" | 统一为 YYYY-MM-DD 格式 |
| status_field | 枚举值越界 | "Unknown", "N/A" | 映射为标准枚举值或标记为缺失 |

### 5.3 异常值分析

使用 IQR 方法检测数值型字段的异常值：

| 字段名 | 异常值数量 | 异常值比例(%) | 处理建议 |
|--------|------------|---------------|----------|
| price | 25 | 2.50 | 异常比例较低，建议保留或使用分位数截断 |
| quantity | 100 | 10.00 | 异常比例较高，建议核实数据来源 |

> 异常值判定标准：Q1 - 1.5*IQR 到 Q3 + 1.5*IQR 范围外的值。

### 5.4 数据质量总评

| 评估维度 | 评分 | 说明 |
|----------|------|------|
| 完整性 | 高/中/低 | {评估说明} |
| 一致性 | 高/中/低 | {评估说明} |
| 准确性 | 高/中/低 | {评估说明} |
| **整体评分** | **高/中/低** | {综合评估} |

### 5.5 数据清洗建议

根据以上分析，建议进行以下数据清洗操作：

1. **缺失值处理**：
   - field_x: 建议 {具体操作}
   - field_y: 建议 {具体操作}

2. **格式标准化**：
   - date_field: 统一日期格式为 YYYY-MM-DD
   - ...

3. **异常值处理**：
   - price: 建议 {具体操作}
   - ...

4. **其他建议**：
   - {其他数据清洗建议}

---

## 6. 附录

### 6.1 分析环境

- 分析时间：{datetime}
- 数据来源：{filename}
- 工具版本：Data Understanding Skill v1.0.0
```

---

## 分析执行指南

### 步骤 1：数据概览
```python
# 获取基本信息
print(f"行数: {df.shape[0]}, 列数: {df.shape[1]}")
print(f"内存占用: {df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB")
print(df.dtypes)

# 识别可能的主键（唯一且非空）
for col in df.columns:
    if df[col].nunique() == len(df) and df[col].notna().all():
        print(f"可能的主键: {col}")
```

### 步骤 2：字段理解
```python
# 基于字段名推测业务含义
# 常见字段名映射示例：
# - id, ID, key -> 标识符
# - name, title -> 名称
# - date, time, datetime -> 时间相关
# - price, amount, cost, fee -> 金额相关
# - qty, quantity, count, num -> 数量相关
# - status, state, type, category -> 分类/状态
# - desc, description, remark, note -> 描述信息
```

### 步骤 3：数值型字段统计
```python
# 识别数值型字段
numeric_cols = df.select_dtypes(include=['int64', 'float64', 'int32', 'float32']).columns.tolist()

# 选取重要字段（如果超过5个）
# 优先级：变异系数大、业务关键字段
if len(numeric_cols) > 5:
    # 计算变异系数选取
    cv = df[numeric_cols].std() / df[numeric_cols].mean()
    important_cols = cv.nlargest(5).index.tolist()
else:
    important_cols = numeric_cols

# 计算统计量
for col in important_cols:
    mean = df[col].mean()
    median = df[col].median()
    std = df[col].std()
    print(f"{col}: 均值={mean:.2f}, 中位数={median:.2f}, 标准差={std:.2f}")
```

### 步骤 4：分类型字段分布
```python
# 识别分类型字段
categorical_cols = df.select_dtypes(include=['object', 'category', 'bool']).columns.tolist()

# 选取重要字段（如果超过5个）
# 优先级：唯一值数量适中（2-20）、非高基数字段
if len(categorical_cols) > 5:
    cardinality = df[categorical_cols].nunique()
    # 选择基数在2-50之间的字段
    good_cols = cardinality[(cardinality >= 2) & (cardinality <= 50)]
    important_cats = good_cols.nsmallest(5).index.tolist()
else:
    important_cats = categorical_cols

# 计算分布
for col in important_cats:
    counts = df[col].value_counts()
    proportions = df[col].value_counts(normalize=True) * 100
    print(f"\n{col}:")
    for val in counts.index[:10]:  # 最多显示前10个类别
        print(f"  {val}: {counts[val]} ({proportions[val]:.2f}%)")
```

### 步骤 5：数据质量评估
```python
# 5.1 完整性 - 缺失值
missing = df.isnull().sum()
missing_pct = (missing / len(df)) * 100
high_missing = missing_pct[missing_pct > 5]

# 5.2 一致性 - 格式检查
# 检查日期字段格式
# 检查枚举字段取值范围

# 5.3 异常值检测 (IQR方法)
for col in numeric_cols:
    Q1 = df[col].quantile(0.25)
    Q3 = df[col].quantile(0.75)
    IQR = Q3 - Q1
    lower = Q1 - 1.5 * IQR
    upper = Q3 + 1.5 * IQR
    outliers = df[(df[col] < lower) | (df[col] > upper)][col]
    outlier_pct = len(outliers) / len(df) * 100
    print(f"{col}: {len(outliers)} 个异常值 ({outlier_pct:.2f}%)")
```

---

## 注意事项

1. **字段含义推测**：根据字段命名规范和数据内容综合判断，对于无法确定含义的字段，明确标注需要补充信息
2. **重要字段选取**：优先选择业务关键字段、变异较大的数值字段、基数适中的分类字段
3. **质量评分标准**：
   - 高：缺失率<5%，无格式问题，异常值<3%
   - 中：缺失率5-15%，有少量格式问题，异常值3-10%
   - 低：缺失率>15%，格式问题严重，异常值>10%
4. **图表生成**：如果执行环境支持 matplotlib/seaborn，为分类字段生成可视化图表
5. **报告完整性**：确保所有模块都有输出，即使某些维度没有问题也要明确说明

---

## 示例触发

用户输入示例：
- "帮我理解这份数据"
- "对数据进行探索性分析"
- "生成数据理解报告"
- "分析数据质量"
- "给我一个数据概览"
