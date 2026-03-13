# frontend-design skill 脚本
# 调用 Claude API 根据用户需求动态生成 HTML 前端页面

import sys

# 获取用户需求
user_requirements = params.get("userRequirements", [])
summary = params.get("summary", "")
context = params.get("context", "")
skill_description = params.get("skillDescription", "")

# 合并所有用户输入
user_input = ""
if context:
    user_input = context
elif summary:
    user_input = summary
elif user_requirements:
    user_input = "\n".join(user_requirements) if isinstance(user_requirements, list) else str(user_requirements)
elif skill_description:
    user_input = skill_description

# 如果没有任何输入，使用默认
if not user_input.strip():
    user_input = "现代化网页设计"

print(f"用户需求: {user_input}")

html_content = None
error_msg = None

try:
    # 动态导入以便捕获错误
    import anthropic

    # 获取项目根目录（通过 SKILL_DIR 反推）
    # SKILL_DIR 是 agent_service.py 传入的技能目录
    project_root = SKILL_DIR.parent.parent
    sys.path.insert(0, str(project_root))

    from config import get_settings
    settings = get_settings()

    # 构建 prompt
    prompt = f"""你是一个专业的前端设计师，请根据用户需求生成一个精美的 HTML 页面。

用户需求：{user_input}

要求：
1. 生成完整的 HTML 文件，包含内联 CSS 样式
2. 设计要现代、美观、专业
3. 使用渐变背景、卡片布局、阴影效果等现代 UI 元素
4. 如果是商城/电商类需求，要包含商品展示、购物车按钮等
5. 根据用户提到的具体内容（如花、酒、服装等）定制页面内容和配色
6. 页面要响应式，适配移动端
7. 使用中文内容
8. 不要使用外部 CSS/JS 库，所有样式内联

直接输出完整的 HTML 代码，不要有任何解释或 markdown 标记。
"""

    # 调用 Claude API
    print("正在调用 Claude API 生成页面...")

    client_kwargs = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        client_kwargs["base_url"] = settings.anthropic_base_url

    client = anthropic.Anthropic(**client_kwargs)

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4000,  # 减少 token 数量加快响应
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    html_content = response.content[0].text

    # 清理可能的 markdown 代码块标记
    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]
    html_content = html_content.strip()

    print("Claude API 调用成功！")

except Exception as e:
    print(f"技能执行失败: {e}")
    import traceback
    traceback.print_exc()
    error_msg = str(e)

# 如果 API 调用失败，生成回退页面
if html_content is None:
    title = user_input[:30] if len(user_input) > 30 else user_input
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: sans-serif; padding: 40px; background: linear-gradient(135deg, #667eea, #764ba2); min-height: 100vh; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 40px; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }}
        h1 {{ color: #1e293b; }}
        p {{ color: #64748b; line-height: 1.8; }}
        .error {{ background: #fee2e2; border: 1px solid #fecaca; padding: 16px; border-radius: 8px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p>页面生成失败，请检查 API 配置或依赖。</p>
        <div class="error">
            <p><strong>错误信息:</strong> {error_msg or '未知错误'}</p>
        </div>
    </div>
</body>
</html>"""

# 生成输出文件
filename = generate_unique_filename("frontend", "html")
filepath = OUTPUTS_DIR / filename
filepath.write_text(html_content, encoding="utf-8")

print(f"已生成文件: {filename}")

# 返回结果
result = {
    "message": "成功生成页面" if error_msg is None else "生成了回退页面",
    "user_input": user_input,
    "error": error_msg,
    "_output_file": {
        "name": filename,
        "type": "html",
        "url": f"/outputs/{filename}",
        "path": str(filepath)
    }
}
