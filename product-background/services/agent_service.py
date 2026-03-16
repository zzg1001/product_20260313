import json
import sys
from io import StringIO
from pathlib import Path
from typing import List, Optional, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session
import anthropic
import pandas as pd
from config import get_settings
from models.skill import Skill
from schemas.agent import SkillPlanItem
from services.file_generator import OUTPUTS_DIR, generate_unique_filename
from routers.logs import log_ai_start, log_ai_done, log_error

settings = get_settings()

# 技能文件夹存储目录
SKILLS_STORAGE_DIR = Path(__file__).parent.parent / "skills_storage"


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        # Support Azure proxy URL if configured
        client_kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = settings.claude_model

    def _get_skills_context(self, skill_ids: Optional[List[str]] = None, load_full_content: bool = False) -> str:
        """Get skills information for AI context

        Args:
            skill_ids: List of skill IDs to filter by
            load_full_content: If True, load full SKILL.md content for each skill
        """
        query = self.db.query(Skill)
        if skill_ids:
            query = query.filter(Skill.id.in_(skill_ids))
        skills = query.all()

        if not skills:
            return "No skills available."

        skills_info = []
        for skill in skills:
            info = f"- ID: {skill.id}, Name: {skill.name}"
            if skill.description:
                info += f", Description: {skill.description}"
            if skill.tags:
                info += f", Tags: {', '.join(skill.tags)}"
            skills_info.append(info)

            # Load full SKILL.md content if requested and skill has folder
            if load_full_content and skill.folder_path:
                skill_folder = SKILLS_STORAGE_DIR / skill.folder_path
                skill_md_path = skill_folder / "SKILL.md"
                if skill_md_path.exists():
                    try:
                        skill_md_content = skill_md_path.read_text(encoding="utf-8")
                        skills_info.append(f"\n--- Full content for {skill.name} ---\n{skill_md_content}\n---\n")
                    except Exception:
                        pass

        return "Available skills:\n" + "\n".join(skills_info)

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        skill_ids: Optional[List[str]] = None
    ) -> str:
        """Simple chat with Claude AI"""
        # Load full content when specific skills are provided
        load_full = skill_ids is not None and len(skill_ids) > 0
        skills_context = self._get_skills_context(skill_ids, load_full_content=load_full)

        system_prompt = f"""你是一个智能AI Agent，能够分析用户需求并规划技能（Skills）执行流程。

{skills_context}

## 核心职责
当用户提出**任务型请求**时，分析并规划技能执行流程。

## 技能规划格式
如果识别到任务请求，在回复末尾添加：
<!--SKILL_PLAN:[{{"skill":"技能名","action":"操作描述","exists":true/false}}]-->

## 回复格式
- 使用 Markdown：**粗体**、`代码`、列表
- 简洁专业，中文回复"""

        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages
        )

        return response.content[0].text

    async def chat_stream(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        skill_ids: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat response from Claude AI"""
        # Load full content when specific skills are provided
        load_full = skill_ids is not None and len(skill_ids) > 0
        skills_context = self._get_skills_context(skill_ids, load_full_content=load_full)

        system_prompt = f"""你是一个智能AI Agent，能够分析用户需求并规划技能（Skills）执行流程。

{skills_context}

## 核心职责
当用户提出**任务型请求**（如"帮我做..."、"我想要..."、"请处理..."、"分析..."、"生成..."等），你需要：
1. 分析任务需要哪些步骤
2. 将步骤映射到可用的 Skills
3. 在回复末尾输出技能规划（使用特定格式）

## 技能规划格式
如果识别到任务请求，请在回复**末尾**添加如下格式（必须是最后一行）：
<!--SKILL_PLAN:[{{"skill":"技能名","action":"操作描述","exists":true/false}}]-->

- `skill`: 技能名称（匹配已有技能用已有名称，否则用建议的新名称，如 data-analyzer）
- `action`: 这一步要做什么
- `exists`: 检查 Available skills 列表判断技能是否存在

## 示例
用户: "帮我分析销售数据并生成报告"

回复:
好的，我来帮你完成这个任务！我规划了以下执行流程：

1. **数据处理** - 使用 `data-processor` 读取和清洗数据
2. **数据分析** - 使用 `data-analyzer` 进行统计分析
3. **报告生成** - 使用 `report-generator` 生成可视化报告

点击下方流程即可开始执行。

<!--SKILL_PLAN:[{{"skill":"data-processor","action":"读取销售数据","exists":true}},{{"skill":"data-analyzer","action":"统计分析","exists":false}},{{"skill":"report-generator","action":"生成报告","exists":false}}]-->

## 回复格式
- 使用 Markdown：**粗体**、`代码`、列表
- 简洁专业，中文回复
- 如果不是任务请求（如闲聊、提问），正常对话，不需要 SKILL_PLAN"""

        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        with self.client.messages.stream(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                yield text

    async def plan_skills(
        self,
        user_input: str,
        available_skill_ids: Optional[List[str]] = None
    ) -> tuple[List[SkillPlanItem], str]:
        """Plan which skills to use based on user input"""
        skills_context = self._get_skills_context(available_skill_ids)

        system_prompt = f"""You are a skill planning assistant. Based on user requirements,
analyze and recommend which skills to use.

{skills_context}

Respond in JSON format with:
{{
    "plan": [
        {{
            "skill_id": "<uuid>",
            "skill_name": "<name>",
            "reason": "<why this skill>",
            "params": {{}}
        }}
    ],
    "explanation": "<overall explanation>"
}}

If no suitable skills are found, return an empty plan with an explanation."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )

        try:
            result = json.loads(response.content[0].text)
            plan_items = [SkillPlanItem(**item) for item in result.get("plan", [])]
            explanation = result.get("explanation", "")
            return plan_items, explanation
        except json.JSONDecodeError:
            return [], "Failed to parse AI response"

    def execute_skill(
        self,
        skill_id: str,
        script_name: Optional[str] = None,
        params: Dict[str, Any] = None
    ) -> tuple[bool, Any, Optional[str], Optional[str]]:
        """
        Execute a skill's script from file system

        Args:
            skill_id: Skill UUID
            script_name: Script filename (default: entry_script from DB)
            params: Parameters to pass to the script

        Returns:
            (success, result, error, output)
        """
        import traceback

        # ========== 调试日志 ==========
        print(f"\n========== [AgentService.execute_skill] ==========")
        print(f"[AgentService] skill_id: {skill_id}")
        print(f"[AgentService] script_name: {script_name}")
        print(f"[AgentService] params type: {type(params)}")
        print(f"[AgentService] params keys: {list(params.keys()) if params else 'None'}")
        print(f"[AgentService] file_path: {params.get('file_path', 'NOT SET') if params else 'NO PARAMS'}")
        print(f"[AgentService] file_paths: {params.get('file_paths', 'NOT SET') if params else 'NO PARAMS'}")
        print(f"[AgentService] Full params: {params}")
        print(f"==================================================\n")

        skill = self.db.query(Skill).filter(Skill.id == skill_id).first()
        if not skill:
            log_error(f"技能不存在: {skill_id}")
            return False, None, "Skill not found", None

        # 确定要执行的脚本
        if not skill.folder_path:
            log_ai_start()
            return self._execute_skill_with_ai_fallback(skill, params)

        skill_folder = SKILLS_STORAGE_DIR / skill.folder_path

        if not skill_folder.exists():
            log_error(f"文件夹不存在: {skill.folder_path}")
            return False, None, f"Skill folder not found: {skill.folder_path}", None

        # 确定脚本文件
        script_file = script_name or skill.entry_script or "main.py"
        script_path = skill_folder / script_file

        if not script_path.exists():
            py_files = [f for f in skill_folder.glob("*.py") if f.name != "__init__.py"]
            if py_files:
                script_path = py_files[0]
            else:
                skill_md_path = skill_folder / "SKILL.md"
                if skill_md_path.exists():
                    log_ai_start()
                    return self._execute_skill_with_ai(skill, skill_folder, params)
                else:
                    log_error(f"未找到脚本: {script_file}")
                    return False, None, f"Script not found: {script_file}", None

        # 读取脚本代码
        try:
            code = script_path.read_text(encoding="utf-8")
        except Exception as e:
            log_error(f"读取脚本失败: {e}")
            traceback.print_exc()
            return False, None, f"Failed to read script: {e}", None

        # 检测代码类型
        has_main_func = "def main(params)" in code or "def main(params:" in code
        if not has_main_func:
            code = self._wrap_code_with_main(code, skill.name)
            has_main_func = True

        # Capture stdout
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        try:
            # Create execution context with params and utilities
            exec_globals = {
                "params": params or {},
                # Skill folder path
                "SKILL_DIR": skill_folder,
                # Data processing libraries
                "pd": pd,
                "pandas": pd,
                # File utilities
                "OUTPUTS_DIR": OUTPUTS_DIR,
                "generate_unique_filename": generate_unique_filename,
                "Path": Path,
                # Built-ins
                "__builtins__": __builtins__,
            }

            # 将技能文件夹添加到 Python 路径
            import sys as _sys
            _sys.path.insert(0, str(skill_folder))

            try:
                # 先加载代码定义
                exec(code, exec_globals)

                # 调用 main(params) 函数
                if "main" in exec_globals and callable(exec_globals["main"]):
                    print(f"\n[AgentService] Calling main() with params:")
                    print(f"[AgentService] file_path: {(params or {}).get('file_path', 'NOT SET')}")
                    print(f"[AgentService] file_paths: {(params or {}).get('file_paths', 'NOT SET')}")
                    result = exec_globals["main"](params or {})
                    exec_globals["result"] = result

            finally:
                # 恢复 Python 路径
                if str(skill_folder) in _sys.path:
                    _sys.path.remove(str(skill_folder))

            output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
            result = exec_globals.get("result", None)

            # 后处理：如果结果是文件路径字符串，转换为标准格式
            if isinstance(result, str) and result:
                result_path = Path(result)
                if result_path.exists() and result_path.is_file():
                    try:
                        file_content = result_path.read_text(encoding='utf-8')
                        suffix = result_path.suffix.lower()
                        file_type = {
                            '.json': 'json',
                            '.html': 'html',
                            '.htm': 'html',
                            '.csv': 'csv',
                            '.txt': 'txt',
                            '.md': 'markdown'
                        }.get(suffix, 'txt')
                        result = {
                            '_output_file': {
                                'path': str(result_path),
                                'type': file_type,
                                'name': result_path.name
                            },
                            'content': file_content,
                            'message': f"文件已生成: {result_path.name}"
                        }
                        output = file_content
                    except Exception:
                        pass

            # 恢复标准输出
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            return True, result, None, output
        except Exception as e:
            output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()

            # 恢复标准输出
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # 记录详细错误
            traceback.print_exc()

            error_msg = f"{type(e).__name__}: {str(e)}"
            return False, None, error_msg, output
        finally:
            # 确保恢复标准输出
            if sys.stdout != old_stdout:
                sys.stdout = old_stdout
            if sys.stderr != old_stderr:
                sys.stderr = old_stderr

    def _execute_skill_with_ai(
        self,
        skill: Skill,
        skill_folder: Path,
        params: Dict[str, Any] = None
    ) -> tuple[bool, Any, Optional[str], Optional[str]]:
        """
        使用 AI 执行技能（基于 SKILL.md 的提示词型技能）

        这类技能没有可执行的 Python 脚本，而是通过 SKILL.md 提供指南，
        让 AI 根据指南和用户需求来完成任务。
        """
        try:
            # ========== 调试日志 ==========
            print(f"\n========== [_execute_skill_with_ai] ==========")
            print(f"[AI Execute] skill.name: {skill.name}")
            print(f"[AI Execute] skill_folder: {skill_folder}")
            print(f"[AI Execute] params: {params}")
            print(f"[AI Execute] file_path in params: {params.get('file_path', 'NOT SET') if params else 'NO PARAMS'}")
            print(f"[AI Execute] file_paths in params: {params.get('file_paths', 'NOT SET') if params else 'NO PARAMS'}")
            print(f"===============================================\n")

            # 读取 SKILL.md
            skill_md_path = skill_folder / "SKILL.md"
            skill_md_content = skill_md_path.read_text(encoding="utf-8")

            # 读取 reference 目录下的文档（如果有）
            reference_content = ""
            reference_dir = skill_folder / "reference"
            if reference_dir.exists():
                for ref_file in reference_dir.glob("*.md"):
                    try:
                        ref_text = ref_file.read_text(encoding="utf-8")
                        # 限制每个参考文件的大小
                        if len(ref_text) > 5000:
                            ref_text = ref_text[:5000] + "\n...[truncated]..."
                        reference_content += f"\n\n## Reference: {ref_file.name}\n{ref_text}"
                    except Exception:
                        pass

            # 获取用户上下文
            context = params.get("context", "") if params else ""
            skill_description = params.get("skillDescription", "") if params else ""
            user_input = context or skill_description or skill.description or ""

            # 获取上传的文件
            file_paths = params.get("file_paths", []) if params else []
            file_path = params.get("file_path", "") if params else ""
            if file_path and file_path not in file_paths:
                file_paths.append(file_path)

            # 读取上传文件的内容
            file_content = ""
            if file_paths:
                file_content = self._read_files_for_ai(file_paths)

            # 检测期望的输出格式
            combined_text = f"{skill.name} {skill.description or ''} {user_input} {skill_md_content[:500]}".lower()
            output_format_hint = ""
            if "json" in combined_text:
                output_format_hint = "用户需要 JSON 格式输出，请直接输出有效的 JSON 数据（不要用 markdown 代码块包裹）。"
            elif "excel" in combined_text or "xlsx" in combined_text or "表格" in combined_text:
                output_format_hint = "用户需要表格数据，请输出 JSON 数组格式的数据，每个元素是一行记录。"
            elif "csv" in combined_text:
                output_format_hint = "用户需要 CSV 格式，请输出 CSV 格式的文本数据。"
            elif any(kw in combined_text for kw in ["html", "网页", "页面", "可视化"]):
                output_format_hint = "用户需要 HTML 格式，请生成完整的 HTML 页面。"
            else:
                output_format_hint = "根据任务性质选择最合适的输出格式。"

            # 构建 prompt
            system_prompt = f"""你是一个专业的 AI 助手，正在执行名为「{skill.name}」的技能。

## 技能说明
{skill_md_content[:8000]}

{reference_content[:4000] if reference_content else ""}

## 任务要求
根据技能说明和用户需求，生成高质量的输出。
- 如果是代码相关技能，生成完整可运行的代码
- 如果是文档相关技能，生成专业的文档内容
- 如果是设计相关技能，生成详细的设计方案

## 输出格式
{output_format_hint}
直接输出结果内容，不需要额外的解释或 markdown 代码块包装（除非内容本身需要）。
"""

            # 构建用户消息，包含文件内容
            user_message = user_input or "请根据技能说明执行默认任务"
            if file_content:
                user_message = f"{user_message}\n\n## 用户上传的文件数据\n{file_content}"

            # 调用 Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            ai_output = response.content[0].text
            log_ai_done()

            # 根据技能类型生成适当的输出文件
            result = {
                "message": f"AI 技能「{skill.name}」执行完成",
                "skill_type": "ai_prompt",
                "content": ai_output
            }

            # 检测输出类型并生成文件
            output_lower = ai_output.strip().lower()
            if output_lower.startswith("<!doctype") or output_lower.startswith("<html"):
                # HTML 输出
                result["_html"] = ai_output

            return True, result, None, ai_output

        except Exception as e:
            import traceback
            traceback.print_exc()
            log_error(f"AI执行失败: {str(e)[:30]}")
            return False, None, f"AI skill execution failed: {str(e)}", None

    def _execute_skill_with_ai_fallback(
        self,
        skill: Skill,
        params: Dict[str, Any] = None
    ) -> tuple[bool, Any, Optional[str], Optional[str]]:
        """
        AI 回退执行 - 当技能没有代码文件夹时，使用 AI 根据技能名称和描述来执行

        这适用于 AI 自动规划的技能（只有名称和描述，没有实际代码）
        """
        try:
            # ========== 调试日志 ==========
            print(f"\n========== [_execute_skill_with_ai_fallback] ==========")
            print(f"[AI Fallback] skill.name: {skill.name}")
            print(f"[AI Fallback] params: {params}")
            print(f"[AI Fallback] file_path in params: {params.get('file_path', 'NOT SET') if params else 'NO PARAMS'}")
            print(f"[AI Fallback] file_paths in params: {params.get('file_paths', 'NOT SET') if params else 'NO PARAMS'}")
            print(f"=======================================================\n")

            # 获取用户上下文
            context = params.get("context", "") if params else ""
            skill_description = params.get("skillDescription", "") if params else ""
            user_input = context or skill_description or ""

            # 获取上传的文件
            file_paths = params.get("file_paths", []) if params else []
            file_path = params.get("file_path", "") if params else ""
            if file_path and file_path not in file_paths:
                file_paths.append(file_path)

            print(f"[AI Fallback] Final file_paths after merge: {file_paths}")

            log_ai_start()

            # 读取上传文件的内容
            file_content = ""
            if file_paths:
                file_content = self._read_files_for_ai(file_paths)

            # 检测期望的输出格式
            combined_text = f"{skill.name} {skill.description or ''} {user_input}".lower()
            output_format_hint = ""
            if "json" in combined_text:
                output_format_hint = "用户需要 JSON 格式输出，请直接输出有效的 JSON 数据（不要用 markdown 代码块包裹）。"
            elif "excel" in combined_text or "xlsx" in combined_text or "表格" in combined_text:
                output_format_hint = "用户需要表格数据，请输出 JSON 数组格式的数据，每个元素是一行记录。"
            elif "csv" in combined_text:
                output_format_hint = "用户需要 CSV 格式，请输出 CSV 格式的文本数据。"
            elif any(kw in combined_text for kw in ["html", "网页", "页面", "可视化", "报告"]):
                output_format_hint = "用户需要 HTML 格式，请生成完整的 HTML 页面。"
            else:
                output_format_hint = "根据任务性质选择最合适的输出格式（JSON、文本或结构化数据）。"

            # 构建 prompt
            system_prompt = f"""你是一个专业的 AI 助手，正在执行名为「{skill.name}」的任务。

## 技能说明
{skill.description or '根据技能名称推断任务内容'}

## 任务要求
根据用户需求，生成高质量的输出。
- 如果任务涉及数据处理，请处理提供的数据并输出结果
- 如果任务涉及数据分析，提供详细的分析结果
- 如果任务涉及代码生成，生成完整可运行的代码
- 如果任务涉及文档撰写，生成专业的文档内容

## 输出格式
{output_format_hint}
直接输出结果内容，不需要额外的解释或说明文字。
"""

            # 构建用户消息，包含文件内容
            user_message = user_input or f"请执行「{skill.name}」任务"
            if file_content:
                user_message = f"{user_message}\n\n## 用户上传的文件数据\n{file_content}"

            # 调用 Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            ai_output = response.content[0].text
            log_ai_done()

            # 构建结果
            result = {
                "message": f"AI 执行「{skill.name}」完成",
                "skill_type": "ai_fallback",
                "content": ai_output
            }

            # 检测输出类型
            output_lower = ai_output.strip().lower()
            if output_lower.startswith("<!doctype") or output_lower.startswith("<html"):
                result["_html"] = ai_output

            return True, result, None, ai_output

        except Exception as e:
            import traceback
            traceback.print_exc()
            log_error(f"AI执行失败: {str(e)[:30]}")
            return False, None, f"AI fallback execution failed: {str(e)}", None

    def _wrap_code_with_main(self, code: str, skill_name: str) -> str:
        """
        为没有 main(params) 的代码自动添加包装
        """
        import re

        # 查找所有定义的函数
        func_pattern = r'def\s+(\w+)\s*\([^)]*\)'
        all_funcs = re.findall(func_pattern, code)

        # 排除辅助函数
        exclude_funcs = {'convert_value', 'helper', 'utils', '__init__', 'setup', 'init'}

        candidates = []
        for func_name in all_funcs:
            if func_name.startswith('_') or func_name in exclude_funcs:
                continue

            score = 0
            func_lower = func_name.lower()

            # 优先级评分
            if 'excel' in func_lower and 'json' in func_lower:
                score = 100
            elif '_to_' in func_lower:
                score = 90
            elif any(kw in func_lower for kw in ['convert', 'transform', 'process', 'parse', 'export']):
                score = 80
            elif any(kw in func_lower for kw in ['excel', 'csv', 'json', 'pdf', 'xml']):
                score = 70
            elif func_lower in ('main', 'run', 'execute'):
                score = 50
            elif any(kw in func_lower for kw in ['read', 'write', 'load', 'save', 'get', 'create']):
                score = 40
            else:
                score = 10

            candidates.append((score, func_name))

        if not candidates:
            return code

        candidates.sort(reverse=True)
        main_func_name = candidates[0][1]

        # 生成包装代码 - 使用 _output_file 以匹配系统的检测逻辑
        wrapper = f'''

# ========== 自动生成的 API 包装 ==========
def main(params):
    import json
    # 兼容两种字段名：file_paths (前端传递) 和 files (旧格式)
    file_paths = params.get('file_paths', []) or params.get('files', [])
    file_path = params.get('file_path', '')

    print(f"[AutoWrapper] params: {{params}}")
    print(f"[AutoWrapper] file_paths: {{file_paths}}, file_path: {{file_path}}")

    if file_paths:
        input_file = file_paths[0]
    elif file_path:
        input_file = file_path
    else:
        return {{'status': 'error', 'message': '请上传文件'}}

    print(f"[AutoWrapper] Calling {main_func_name} with: {{input_file}}")

    try:
        result = {main_func_name}(input_file)
        print(f"[AutoWrapper] Result type: {{type(result)}}, value: {{str(result)[:200]}}")

        if isinstance(result, str):
            try:
                json.loads(result)
                output_path = OUTPUTS_DIR / generate_unique_filename('output', 'json')
                output_path.write_text(result, encoding='utf-8')
                return {{
                    'status': 'success',
                    'message': '转换完成',
                    'content': result,
                    '_output_file': {{'path': str(output_path), 'type': 'json', 'name': output_path.name, 'url': f'/outputs/{{output_path.name}}'}}
                }}
            except json.JSONDecodeError:
                return {{'status': 'success', 'message': result, 'content': result}}
        elif isinstance(result, (dict, list)):
            json_str = json.dumps(result, ensure_ascii=False, indent=2)
            output_path = OUTPUTS_DIR / generate_unique_filename('output', 'json')
            output_path.write_text(json_str, encoding='utf-8')
            return {{
                'status': 'success',
                'message': '处理完成',
                'content': result,
                '_output_file': {{'path': str(output_path), 'type': 'json', 'name': output_path.name, 'url': f'/outputs/{{output_path.name}}'}}
            }}
        else:
            return {{'status': 'success', 'message': str(result), 'content': str(result)}}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {{'status': 'error', 'message': str(e)}}
'''
        return code + wrapper

    def _read_files_for_ai(self, file_paths: list) -> str:
        """
        读取上传的文件内容，转换为 AI 可以处理的文本格式
        """
        contents = []

        for file_path in file_paths:
            try:
                path = Path(file_path)
                if not path.exists():
                    continue

                suffix = path.suffix.lower()

                # Excel 文件
                if suffix in ['.xlsx', '.xls']:
                    try:
                        df = pd.read_excel(file_path)
                        # 限制行数避免 token 过多
                        if len(df) > 500:
                            df = df.head(500)
                            contents.append(f"### {path.name} (前500行)\n```\n{df.to_string()}\n```")
                        else:
                            contents.append(f"### {path.name}\n```\n{df.to_string()}\n```")
                    except Exception:
                        pass

                # CSV 文件
                elif suffix == '.csv':
                    try:
                        df = pd.read_csv(file_path)
                        if len(df) > 500:
                            df = df.head(500)
                            contents.append(f"### {path.name} (前500行)\n```\n{df.to_string()}\n```")
                        else:
                            contents.append(f"### {path.name}\n```\n{df.to_string()}\n```")
                    except Exception:
                        pass

                # JSON 文件
                elif suffix == '.json':
                    try:
                        import json
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        json_str = json.dumps(data, ensure_ascii=False, indent=2)
                        if len(json_str) > 10000:
                            json_str = json_str[:10000] + "\n...[truncated]..."
                        contents.append(f"### {path.name}\n```json\n{json_str}\n```")
                    except Exception:
                        pass

                # 文本文件
                elif suffix in ['.txt', '.md', '.py', '.js', '.html', '.css']:
                    try:
                        text = path.read_text(encoding='utf-8')
                        if len(text) > 10000:
                            text = text[:10000] + "\n...[truncated]..."
                        contents.append(f"### {path.name}\n```\n{text}\n```")
                    except Exception:
                        pass

                else:
                    contents.append(f"### {path.name}\n[不支持的文件类型: {suffix}]")

            except Exception:
                pass

        return "\n\n".join(contents)

    def execute_temp_skill(
        self,
        temp_folder: Path,
        skill_name: str,
        script_name: Optional[str] = None,
        params: Dict[str, Any] = None
    ) -> tuple[bool, Any, Optional[str], Optional[str]]:
        """
        执行临时技能（用于测试）

        Args:
            temp_folder: 临时技能文件夹路径
            skill_name: 技能名称
            script_name: 脚本文件名（可选）
            params: 执行参数

        Returns:
            (success, result, error, output)
        """
        import traceback

        if not temp_folder.exists():
            return False, None, "临时技能文件夹不存在", None

        # 查找可执行脚本
        script_file = script_name or "main.py"
        script_path = temp_folder / script_file

        if not script_path.exists():
            # 尝试查找任意 .py 文件
            py_files = [f for f in temp_folder.glob("*.py") if f.name != "__init__.py"]
            if py_files:
                script_path = py_files[0]
            else:
                # 检查 SKILL.md（AI 型技能）
                skill_md_path = temp_folder / "SKILL.md"
                if skill_md_path.exists():
                    return self._execute_temp_skill_with_ai(temp_folder, skill_name, params)
                else:
                    return False, None, "未找到可执行脚本", None

        # 读取并执行脚本
        try:
            code = script_path.read_text(encoding="utf-8")
        except Exception as e:
            return False, None, f"读取脚本失败: {e}", None

        # 执行脚本
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        try:
            exec_globals = {
                "params": params or {},
                "SKILL_DIR": temp_folder,
                "pd": pd,
                "pandas": pd,
                "OUTPUTS_DIR": OUTPUTS_DIR,
                "generate_unique_filename": generate_unique_filename,
                "Path": Path,
            }
            exec_globals["__builtins__"] = __builtins__

            # 检测代码类型
            has_main_func = "def main(params)" in code or "def main(params:" in code

            exec(code, exec_globals)

            # 如果有 main(params) 函数，调用它
            if has_main_func and "main" in exec_globals and callable(exec_globals["main"]):
                result = exec_globals["main"](params or {})
                exec_globals["result"] = result
            else:
                result = exec_globals.get("result")

            stdout_output = sys.stdout.getvalue()

            return True, result, None, stdout_output

        except Exception as e:
            stderr_output = sys.stderr.getvalue()
            stdout_output = sys.stdout.getvalue()
            output = stdout_output + ("\n" + stderr_output if stderr_output else "")
            traceback.print_exc()
            return False, None, f"{type(e).__name__}: {str(e)}", output

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _execute_temp_skill_with_ai(
        self,
        temp_folder: Path,
        skill_name: str,
        params: Dict[str, Any] = None
    ) -> tuple[bool, Any, Optional[str], Optional[str]]:
        """
        使用 AI 执行临时技能
        """
        try:
            skill_md_path = temp_folder / "SKILL.md"
            skill_md_content = skill_md_path.read_text(encoding="utf-8")

            context = params.get("context", "") if params else ""
            user_input = context or params.get("input", "") if params else ""

            # 获取上传的文件
            file_paths = params.get("file_paths", []) if params else []
            file_path = params.get("file_path", "") if params else ""
            if file_path and file_path not in file_paths:
                file_paths.append(file_path)

            # 读取上传文件的内容
            file_content = ""
            if file_paths:
                file_content = self._read_files_for_ai(file_paths)

            # 检测期望的输出格式
            combined_text = f"{skill_name} {skill_md_content[:500]} {user_input}".lower()
            output_format_hint = ""
            if "json" in combined_text:
                output_format_hint = "用户需要 JSON 格式输出，请直接输出有效的 JSON 数据。"
            elif "excel" in combined_text or "xlsx" in combined_text:
                output_format_hint = "请输出 JSON 数组格式的数据。"

            system_prompt = f"""你是一个专业的 AI 助手，正在测试名为「{skill_name}」的技能。

## 技能说明
{skill_md_content[:8000]}

## 任务要求
根据技能说明和用户需求，生成高质量的输出。
{output_format_hint}

## 输出格式
直接输出结果内容。
"""

            # 构建用户消息，包含文件内容
            user_message = user_input or "请根据技能说明执行测试任务"
            if file_content:
                user_message = f"{user_message}\n\n## 用户上传的文件数据\n{file_content}"

            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            ai_output = response.content[0].text
            result = {
                "message": f"AI 测试「{skill_name}」完成",
                "skill_type": "ai_temp",
                "content": ai_output
            }

            return True, result, None, ai_output

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, None, f"AI 执行失败: {str(e)}", None
