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

    def _get_skills_context(self, skill_ids: Optional[List[str]] = None) -> str:
        """Get skills information for AI context"""
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

        return "Available skills:\n" + "\n".join(skills_info)

    async def chat(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        skill_ids: Optional[List[str]] = None
    ) -> str:
        """Simple chat with Claude AI"""
        skills_context = self._get_skills_context(skill_ids)

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
        skills_context = self._get_skills_context(skill_ids)

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

        print(f"\n{'='*60}")
        print(f"[Skill Execute] Starting execution for skill_id: {skill_id}")
        print(f"{'='*60}")

        skill = self.db.query(Skill).filter(Skill.id == skill_id).first()
        if not skill:
            print(f"[Skill Execute] ERROR: Skill not found: {skill_id}")
            return False, None, "Skill not found", None

        print(f"[Skill Execute] Skill found: {skill.name}")
        print(f"[Skill Execute] Skill folder_path: {skill.folder_path}")
        print(f"[Skill Execute] Skill entry_script: {skill.entry_script}")

        # 确定要执行的脚本
        if not skill.folder_path:
            print(f"[Skill Execute] Skill has no folder, using AI fallback execution...")
            # 没有文件夹的技能，使用 AI 来执行（基于技能名称和描述）
            return self._execute_skill_with_ai_fallback(skill, params)

        skill_folder = SKILLS_STORAGE_DIR / skill.folder_path
        print(f"[Skill Execute] Full skill folder path: {skill_folder}")

        if not skill_folder.exists():
            print(f"[Skill Execute] ERROR: Skill folder not found: {skill_folder}")
            return False, None, f"Skill folder not found: {skill.folder_path}", None

        # 确定脚本文件
        script_file = script_name or skill.entry_script or "main.py"
        script_path = skill_folder / script_file
        print(f"[Skill Execute] Looking for script: {script_path}")

        if not script_path.exists():
            print(f"[Skill Execute] Script not found at {script_path}, searching for .py files...")
            # 尝试查找任意 .py 文件（排除 __init__.py 和 scripts 目录下的文件）
            py_files = [f for f in skill_folder.glob("*.py") if f.name != "__init__.py"]
            print(f"[Skill Execute] Found .py files: {[f.name for f in py_files]}")
            if py_files:
                script_path = py_files[0]
                print(f"[Skill Execute] Using script: {script_path}")
            else:
                # 没有可执行的 Python 脚本，检查是否有 SKILL.md（AI 型技能）
                skill_md_path = skill_folder / "SKILL.md"
                if skill_md_path.exists():
                    print(f"[Skill Execute] Found SKILL.md, using AI execution")
                    # 使用 AI 执行技能
                    return self._execute_skill_with_ai(skill, skill_folder, params)
                else:
                    print(f"[Skill Execute] ERROR: No executable script found")
                    # 列出文件夹内容帮助调试
                    try:
                        files = list(skill_folder.iterdir())
                        print(f"[Skill Execute] Folder contents: {[f.name for f in files]}")
                    except Exception:
                        pass
                    return False, None, f"Script not found: {script_file}", None

        # 读取脚本代码
        try:
            code = script_path.read_text(encoding="utf-8")
            print(f"[Skill Execute] Script loaded, length: {len(code)} chars")
        except Exception as e:
            print(f"[Skill Execute] ERROR: Failed to read script: {e}")
            traceback.print_exc()
            return False, None, f"Failed to read script: {e}", None

        # Capture stdout
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        # 调试：打印接收到的参数
        print(f"[Skill Execute] Received params: {params}")

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
                exec(code, exec_globals)
            finally:
                # 恢复 Python 路径
                if str(skill_folder) in _sys.path:
                    _sys.path.remove(str(skill_folder))

            output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
            result = exec_globals.get("result", None)

            # 恢复标准输出后打印日志
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            print(f"[Skill Execute] SUCCESS: Skill '{skill.name}' executed successfully")
            if output:
                print(f"[Skill Execute] Output:\n{output[:500]}{'...' if len(output) > 500 else ''}")
            if stderr_output:
                print(f"[Skill Execute] Stderr:\n{stderr_output[:500]}")
            print(f"[Skill Execute] Result type: {type(result)}")

            return True, result, None, output
        except Exception as e:
            output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()

            # 恢复标准输出后打印错误日志
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # 打印详细错误信息
            print(f"\n{'!'*60}")
            print(f"[Skill Execute] FAILED: Skill '{skill.name}' execution failed!")
            print(f"{'!'*60}")
            print(f"[Skill Execute] Error Type: {type(e).__name__}")
            print(f"[Skill Execute] Error Message: {str(e)}")
            print(f"[Skill Execute] Script Path: {script_path}")
            print(f"[Skill Execute] Params: {params}")
            print(f"\n[Skill Execute] Full Traceback:")
            traceback.print_exc()
            if output:
                print(f"\n[Skill Execute] Captured stdout:\n{output}")
            if stderr_output:
                print(f"\n[Skill Execute] Captured stderr:\n{stderr_output}")
            print(f"{'!'*60}\n")

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
直接输出结果内容，不需要额外的解释或 markdown 代码块包装（除非内容本身需要）。
"""

            # 调用 Claude API
            print(f"[AI Skill] Executing skill '{skill.name}' with AI...")
            print(f"[AI Skill] User input: {user_input[:200]}...")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_input or "请根据技能说明执行默认任务"}]
            )

            ai_output = response.content[0].text
            print(f"[AI Skill] AI response length: {len(ai_output)}")

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
            print(f"\n{'!'*60}")
            print(f"[AI Skill] FAILED: AI skill '{skill.name}' execution failed!")
            print(f"{'!'*60}")
            print(f"[AI Skill] Error Type: {type(e).__name__}")
            print(f"[AI Skill] Error Message: {str(e)}")
            print(f"\n[AI Skill] Full Traceback:")
            traceback.print_exc()
            print(f"{'!'*60}\n")
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
            # 获取用户上下文
            context = params.get("context", "") if params else ""
            skill_description = params.get("skillDescription", "") if params else ""
            user_input = context or skill_description or ""

            print(f"[AI Fallback] Executing skill '{skill.name}' with AI")
            print(f"[AI Fallback] Skill description: {skill.description}")
            print(f"[AI Fallback] User input: {user_input[:200]}...")

            # 构建 prompt
            system_prompt = f"""你是一个专业的 AI 助手，正在执行名为「{skill.name}」的任务。

## 技能说明
{skill.description or '根据技能名称推断任务内容'}

## 任务要求
根据用户需求，生成高质量的输出。
- 如果任务涉及数据分析，提供详细的分析结果
- 如果任务涉及代码生成，生成完整可运行的代码
- 如果任务涉及文档撰写，生成专业的文档内容

## 输出格式
直接输出结果内容，不需要额外的解释。
如果适合生成 HTML 页面（如报告、可视化），请生成完整的 HTML。
"""

            # 调用 Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_input or f"请执行「{skill.name}」任务"}]
            )

            ai_output = response.content[0].text
            print(f"[AI Fallback] AI response length: {len(ai_output)}")

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
            print(f"\n{'!'*60}")
            print(f"[AI Fallback] FAILED: AI fallback for '{skill.name}' failed!")
            print(f"{'!'*60}")
            print(f"[AI Fallback] Error: {type(e).__name__}: {str(e)}")
            traceback.print_exc()
            print(f"{'!'*60}\n")
            return False, None, f"AI fallback execution failed: {str(e)}", None
