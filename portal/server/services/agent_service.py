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
from models.ccconfig import CCConfig
from schemas.agent import SkillPlanItem
from services.file_generator import OUTPUTS_DIR, generate_unique_filename
from routers.logs import log_ai_start, log_ai_done, log_error

settings = get_settings()

# 技能文件夹存储目录
SKILLS_STORAGE_DIR = Path(__file__).parent.parent / "skills_storage"


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self._init_client()

    def _init_client(self):
        """初始化 Claude 客户端，优先使用数据库中的配置"""
        # 尝试从数据库获取启用的配置
        active_config = self.db.query(CCConfig).filter(CCConfig.is_active == True).first()

        if active_config:
            # 使用数据库配置
            client_kwargs = {"api_key": active_config.api_key}
            if active_config.base_url:
                client_kwargs["base_url"] = active_config.base_url
            self.client = anthropic.Anthropic(**client_kwargs)
            self.model = active_config.model_id
            self.max_tokens = active_config.max_tokens or 4096
            self.temperature = active_config.temperature or 0.7
            self.system_prompt_prefix = active_config.system_prompt or ""
            print(f"[AgentService] 使用数据库配置: {active_config.name} ({active_config.model_id})")
        else:
            # 回退到环境变量配置
            client_kwargs = {"api_key": settings.anthropic_api_key}
            if settings.anthropic_base_url:
                client_kwargs["base_url"] = settings.anthropic_base_url
            self.client = anthropic.Anthropic(**client_kwargs)
            self.model = settings.claude_model
            self.max_tokens = 4096
            self.temperature = 0.7
            self.system_prompt_prefix = ""
            print(f"[AgentService] 使用环境变量配置: {settings.claude_model}")

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

## 多文件处理规则
**重要**：当用户上传多个文件时，同一类型的文件应由**同一个技能**一次性处理，不要为每个文件创建单独的步骤。

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

## 多文件处理规则
**重要**：当用户上传多个文件时：
- 同一类型的文件应由**同一个技能**一次性处理（技能会接收所有文件路径）
- 不要为每个文件创建单独的技能步骤
- 例如：用户上传4个Excel文件要求分析，只需要1个 `data-understanding` 技能，不是4个

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

    def _build_multimodal_content(self, text: str, file_content: str) -> list:
        """
        构建多模态消息内容，支持文本和图片

        从 file_content 中提取图片标记 [IMAGE:mime_type:base64_data]
        并转换为 Claude API 的多模态格式
        """
        import re

        content_parts = []

        # 添加用户文本
        if text:
            content_parts.append({"type": "text", "text": text})

        if not file_content:
            # 如果没有文件内容，返回简单格式
            return text if not content_parts else content_parts

        # 提取图片标记
        image_pattern = r'\[IMAGE:(image/[^:]+):([A-Za-z0-9+/=]+)\]'
        images = re.findall(image_pattern, file_content)

        # 移除图片标记，保留其他文本内容
        text_content = re.sub(image_pattern, '[图片已作为独立内容传递]', file_content)

        if text_content.strip():
            content_parts.append({
                "type": "text",
                "text": f"\n\n## 用户上传的文件数据\n{text_content}"
            })

        # 添加图片
        for mime_type, base64_data in images:
            content_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": base64_data
                }
            })

        return content_parts if content_parts else text

    def _parse_output_format(self, ai_output: str) -> tuple[Optional[str], str]:
        """
        解析 AI 输出中的格式声明标记

        AI 输出格式：
        <!--OUTPUT_FORMAT:md-->
        实际内容...

        Returns:
            (format, clean_content): 格式类型和去除标记后的内容
        """
        import re
        import base64

        # 匹配格式声明标记
        pattern = r'^<!--OUTPUT_FORMAT:(\w+)-->\s*'
        match = re.match(pattern, ai_output.strip(), re.IGNORECASE)

        if match:
            output_format = match.group(1).lower()
            clean_content = re.sub(pattern, '', ai_output.strip(), count=1, flags=re.IGNORECASE)
            return output_format, clean_content.strip()

        # 如果没有显式声明，尝试智能检测
        content_lower = ai_output.strip().lower()

        # SVG 检测
        if content_lower.startswith("<svg") or content_lower.startswith("<?xml") and "<svg" in content_lower:
            return "svg", ai_output

        # HTML 检测
        if content_lower.startswith(("<!doctype", "<html")):
            return "html", ai_output

        # Markdown 检测（以 # 开头的标题）
        if ai_output.strip().startswith("#"):
            return "md", ai_output

        # JSON 检测
        if (content_lower.startswith("{") and content_lower.endswith("}")) or \
           (content_lower.startswith("[") and content_lower.endswith("]")):
            try:
                json.loads(ai_output.strip())
                return "json", ai_output
            except json.JSONDecodeError:
                pass

        # 默认返回无格式
        return None, ai_output

    def _execute_image_code(self, code: str, skill_name: str) -> Optional[dict]:
        """
        执行图片生成代码（matplotlib/PIL）

        Returns:
            {"path": ..., "type": ..., "name": ..., "url": ...} 或 None
        """
        import tempfile
        import subprocess

        try:
            # 创建临时脚本
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                # 添加保存图片的代码
                output_path = OUTPUTS_DIR / f"{skill_name}_{int(__import__('time').time())}.png"
                wrapped_code = f"""
import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt

{code}

# 自动保存图片
plt.savefig(r'{output_path}', dpi=150, bbox_inches='tight')
plt.close()
print(r'{output_path}')
"""
                f.write(wrapped_code)
                script_path = f.name

            # 执行脚本
            result = subprocess.run(
                ['python', script_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            # 清理临时文件
            Path(script_path).unlink(missing_ok=True)

            if result.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size
                return {
                    "path": str(output_path),
                    "type": "png",
                    "name": output_path.name,
                    "url": f"/outputs/{output_path.name}",
                    "size": file_size
                }
        except Exception as e:
            print(f"[Image Code] Execution failed: {e}")

        return None

    def _execute_img_process_code(self, code: str, skill_name: str, input_paths: list) -> Optional[dict]:
        """
        执行图片处理代码（PIL/Pillow）

        Args:
            code: PIL 处理代码
            skill_name: 技能名称
            input_paths: 输入图片路径列表

        Returns:
            {"path": ..., "type": ..., "name": ..., "url": ...} 或 None
        """
        import tempfile
        import subprocess
        import time

        if not input_paths:
            print("[Img Process] No input images provided")
            return None

        # 取第一个图片作为输入
        input_path = input_paths[0]
        if not Path(input_path).exists():
            print(f"[Img Process] Input file not found: {input_path}")
            return None

        try:
            # 生成输出路径
            timestamp = int(time.time())
            output_filename = f"{skill_name}_processed_{timestamp}.png"
            output_path = OUTPUTS_DIR / output_filename

            # 创建临时脚本
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                # 注入 INPUT_PATH 和 OUTPUT_PATH
                wrapped_code = f"""
# 系统注入的路径变量
INPUT_PATH = r'{input_path}'
OUTPUT_PATH = r'{output_path}'

{code}
"""
                f.write(wrapped_code)
                script_path = f.name

            # 执行脚本
            result = subprocess.run(
                ['python', script_path],
                capture_output=True,
                text=True,
                timeout=120  # 图片处理可能需要更长时间
            )

            # 清理临时文件
            Path(script_path).unlink(missing_ok=True)

            if result.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size
                return {
                    "path": str(output_path),
                    "type": "png",
                    "name": output_filename,
                    "url": f"/outputs/{output_filename}",
                    "size": file_size
                }
            else:
                print(f"[Img Process] Execution failed: {result.stderr}")

        except Exception as e:
            print(f"[Img Process] Execution failed: {e}")

        return None

    def _execute_analysis_code(self, code: str, file_paths: list, timeout: int = 120) -> dict:
        """
        执行数据分析代码（通用 Python 分析）

        支持库: pandas, numpy, matplotlib, seaborn, scipy, json, datetime
        安全机制: subprocess 隔离, 超时控制, 目录沙箱

        Args:
            code: Python 分析代码
            file_paths: 输入文件路径列表
            timeout: 执行超时秒数

        Returns:
            {
                'success': bool,
                'stdout': str,
                'stderr': str,
                'generated_files': list,
                'error': str (if failed)
            }
        """
        import tempfile
        import subprocess
        import time
        import glob

        try:
            # 生成时间戳用于输出文件
            timestamp = int(time.time())
            output_prefix = f"analysis_{timestamp}"

            # 安全检查：禁止危险操作
            dangerous_patterns = [
                'os.system', 'subprocess.', 'eval(', 'exec(',
                '__import__', 'open(', 'with open',
                'shutil.rmtree', 'os.remove', 'os.unlink',
                'importlib', 'compile('
            ]

            code_lower = code.lower()
            for pattern in dangerous_patterns:
                if pattern.lower() in code_lower:
                    # 允许 open 用于读取
                    if pattern in ['open(', 'with open']:
                        # 检查是否只是读取模式
                        if "'w'" not in code and '"w"' not in code and "'a'" not in code and '"a"' not in code:
                            continue
                    return {
                        'success': False,
                        'stdout': '',
                        'stderr': f'安全限制：禁止使用 {pattern}',
                        'generated_files': [],
                        'error': f'代码包含不允许的操作: {pattern}'
                    }

            # 构建文件路径列表字符串
            file_paths_str = repr(file_paths)

            # 创建临时脚本
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                wrapped_code = f'''
# -*- coding: utf-8 -*-
import sys
import os

# 设置工作目录
os.chdir(r'{OUTPUTS_DIR}')

# 系统注入的变量
FILE_PATHS = {file_paths_str}
OUTPUT_DIR = r'{OUTPUTS_DIR}'
OUTPUT_PREFIX = '{output_prefix}'

# 导入常用库
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta

# 可选导入
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
except ImportError:
    plt = None

try:
    import seaborn as sns
except ImportError:
    sns = None

try:
    from scipy import stats
except ImportError:
    stats = None

# 辅助函数：保存图表
def save_figure(name=None):
    if plt is None:
        return None
    fig_name = name or f'{{OUTPUT_PREFIX}}_figure.png'
    if not fig_name.endswith('.png'):
        fig_name += '.png'
    fig_path = os.path.join(OUTPUT_DIR, fig_name)
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[GENERATED_FILE]{{fig_path}}')
    return fig_path

# 辅助函数：保存数据
def save_data(data, name=None, format='csv'):
    if isinstance(data, pd.DataFrame):
        file_name = name or f'{{OUTPUT_PREFIX}}_data.{{format}}'
        file_path = os.path.join(OUTPUT_DIR, file_name)
        if format == 'csv':
            data.to_csv(file_path, index=False, encoding='utf-8-sig')
        elif format == 'excel':
            data.to_excel(file_path, index=False)
        elif format == 'json':
            data.to_json(file_path, orient='records', force_ascii=False, indent=2)
        print(f'[GENERATED_FILE]{{file_path}}')
        return file_path
    elif isinstance(data, (dict, list)):
        file_name = name or f'{{OUTPUT_PREFIX}}_data.json'
        file_path = os.path.join(OUTPUT_DIR, file_name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f'[GENERATED_FILE]{{file_path}}')
        return file_path
    return None

# ========== 用户代码开始 ==========
{code}
# ========== 用户代码结束 ==========
'''
                f.write(wrapped_code)
                script_path = f.name

            # 执行脚本
            result = subprocess.run(
                ['python', script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(OUTPUTS_DIR)
            )

            # 清理临时文件
            Path(script_path).unlink(missing_ok=True)

            # 解析生成的文件
            generated_files = []
            for line in result.stdout.split('\n'):
                if line.startswith('[GENERATED_FILE]'):
                    file_path = line.replace('[GENERATED_FILE]', '').strip()
                    if Path(file_path).exists():
                        generated_files.append({
                            'path': file_path,
                            'name': Path(file_path).name,
                            'url': f"/outputs/{Path(file_path).name}",
                            'size': Path(file_path).stat().st_size
                        })

            # 清理输出中的 [GENERATED_FILE] 标记
            clean_stdout = '\n'.join([
                line for line in result.stdout.split('\n')
                if not line.startswith('[GENERATED_FILE]')
            ]).strip()

            return {
                'success': result.returncode == 0,
                'stdout': clean_stdout,
                'stderr': result.stderr,
                'generated_files': generated_files,
                'error': result.stderr if result.returncode != 0 else None
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'stdout': '',
                'stderr': f'执行超时（{timeout}秒）',
                'generated_files': [],
                'error': f'代码执行超时，超过 {timeout} 秒限制'
            }
        except Exception as e:
            import traceback
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'generated_files': [],
                'error': f'执行错误: {str(e)}'
            }

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
                # Simulate __file__ for scripts that use it
                "__file__": str(script_path),
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

            # 即使失败也返回有用的信息
            error_result = {
                "message": f"技能执行出错: {error_msg}",
                "error": error_msg,
                "stdout": output,
                "stderr": stderr_output,
                "_error_details": True
            }

            # 仍然返回 True，让前端能显示错误详情而不是模糊提示
            return True, error_result, None, f"执行出错: {error_msg}\n{stderr_output}"
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

            # 构建 prompt - 让 AI 自己决定输出格式
            system_prompt = f"""你是一个专业的 AI 助手，正在执行名为「{skill.name}」的技能。

## 技能说明
{skill_md_content[:8000]}

{reference_content[:4000] if reference_content else ""}

## 任务要求
根据技能说明和用户需求，生成高质量的输出。

## 输出格式规范（重要！）
你必须在输出的第一行添加格式声明标记，格式为：
<!--OUTPUT_FORMAT:文件扩展名-->

### 文本类格式
- md: Markdown 文档、报告、分析结果
- html: 网页、可视化页面、交互式图表
- json: 结构化数据、API 响应
- csv: 表格数据
- txt: 纯文本
- py/js/ts/java 等: 代码文件

### 图片/图表格式
- svg: 矢量图（流程图、架构图、简单图表）- 直接输出 SVG 代码
- png_code: 数据可视化图表，输出 matplotlib Python 代码，系统会自动执行生成图片
- img_code: 图片处理/增强，输出 PIL/Pillow Python 代码，系统会自动执行处理图片
- analysis_code: 数据分析代码，支持 pandas/numpy/matplotlib/seaborn，系统会执行并返回结果
- html: 交互式图表推荐使用 HTML + Chart.js/ECharts

### 示例

文档输出：
<!--OUTPUT_FORMAT:md-->
# 报告标题
...内容...

SVG 图表：
<!--OUTPUT_FORMAT:svg-->
<svg viewBox="0 0 400 300">...</svg>

matplotlib 图表：
<!--OUTPUT_FORMAT:png_code-->
import matplotlib.pyplot as plt
plt.plot([1,2,3], [4,5,6])
plt.title('示例图表')

图片处理（增强、滤镜、调整等）：
<!--OUTPUT_FORMAT:img_code-->
from PIL import Image, ImageEnhance, ImageFilter
# INPUT_PATH 和 OUTPUT_PATH 由系统自动注入
img = Image.open(INPUT_PATH)
# 锐化
enhancer = ImageEnhance.Sharpness(img)
img = enhancer.enhance(1.5)
# 对比度
enhancer = ImageEnhance.Contrast(img)
img = enhancer.enhance(1.2)
img.save(OUTPUT_PATH)

数据分析（推荐用于数据理解任务）：
<!--OUTPUT_FORMAT:analysis_code-->
# FILE_PATHS 由系统自动注入，包含所有输入文件
df = pd.read_excel(FILE_PATHS[0])
print(df.describe())
print(df.info())
# 可以使用 save_figure() 保存图表，save_data(df) 保存数据

请根据任务性质选择最合适的输出格式，然后输出内容。不要输出额外的解释。
"""

            # 构建用户消息，包含文件内容（支持多模态）
            user_message = user_input or "请根据技能说明执行默认任务"
            message_content = self._build_multimodal_content(user_message, file_content)

            # 调用 Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": message_content}]
            )

            ai_output = response.content[0].text
            log_ai_done()

            # 解析 AI 声明的输出格式
            output_format, clean_content = self._parse_output_format(ai_output)
            print(f"[AI Execute] Detected output format: {output_format}")

            # 根据技能类型生成适当的输出文件
            result = {
                "message": f"AI 技能「{skill.name}」执行完成",
                "skill_type": "ai_prompt",
                "content": clean_content
            }

            # 根据 AI 声明的格式生成文件
            if output_format == "html" or clean_content.strip().lower().startswith(("<!doctype", "<html")):
                result["_html"] = clean_content
            elif output_format == "png_code":
                # 执行 matplotlib 代码生成图片
                image_result = self._execute_image_code(clean_content, skill.name)
                if image_result:
                    result["_output_file"] = image_result
                    result["content"] = f"图表已生成: {image_result['name']}"
                else:
                    # 执行失败，保存为 py 文件供调试
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["message"] = "图表代码生成完成（执行失败，已保存为 .py 文件）"
            elif output_format == "img_code":
                # 执行 PIL 图片处理代码
                image_result = self._execute_img_process_code(clean_content, skill.name, file_paths)
                if image_result:
                    result["_output_file"] = image_result
                    result["content"] = f"图片处理完成: {image_result['name']}"
                else:
                    # 执行失败，保存为 py 文件供调试
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["message"] = "图片处理代码生成完成（执行失败，已保存为 .py 文件）"
            elif output_format == "analysis_code":
                # 执行数据分析代码
                analysis_result = self._execute_analysis_code(clean_content, file_paths)
                if analysis_result['success']:
                    result["content"] = analysis_result['stdout']
                    result["message"] = f"AI 技能「{skill.name}」分析完成"
                    result["_analysis_result"] = {
                        'stdout': analysis_result['stdout'],
                        'generated_files': analysis_result['generated_files']
                    }
                    # 如果生成了文件，返回第一个作为主输出
                    if analysis_result['generated_files']:
                        result["_output_file"] = analysis_result['generated_files'][0]
                        if len(analysis_result['generated_files']) > 1:
                            result["_additional_files"] = analysis_result['generated_files'][1:]
                else:
                    # 执行失败，保存代码供调试
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["content"] = f"代码执行失败:\n{analysis_result['stderr']}\n\n代码已保存为: {filename}"
                    result["message"] = "数据分析代码执行失败（已保存代码供调试）"
            elif output_format and output_format != "txt":
                # 生成对应格式的文件
                filename = generate_unique_filename(skill.name, output_format)
                filepath = OUTPUTS_DIR / filename
                filepath.write_text(clean_content, encoding="utf-8")
                file_size = filepath.stat().st_size
                result["_output_file"] = {
                    "path": str(filepath),
                    "type": output_format,
                    "name": filename,
                    "url": f"/outputs/{filename}",
                    "size": file_size
                }

            return True, result, None, clean_content

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

            # 构建 prompt - 让 AI 自己决定输出格式
            system_prompt = f"""你是一个专业的 AI 助手，正在执行名为「{skill.name}」的任务。

## 技能说明
{skill.description or '根据技能名称推断任务内容'}

## 任务要求
根据用户需求，生成高质量的输出。

## 输出格式规范（重要！）
你必须在输出的第一行添加格式声明标记，格式为：
<!--OUTPUT_FORMAT:文件扩展名-->

### 文本类格式
- md: Markdown 文档、报告、分析结果
- html: 网页、可视化页面、交互式图表
- json: 结构化数据、API 响应
- csv: 表格数据
- txt: 纯文本
- py/js/ts/java 等: 代码文件

### 图片/图表格式
- svg: 矢量图（流程图、架构图、简单图表）- 直接输出 SVG 代码
- png_code: 数据可视化图表，输出 matplotlib Python 代码，系统会自动执行生成图片
- img_code: 图片处理/增强，输出 PIL/Pillow Python 代码，系统会自动执行处理图片
- analysis_code: 数据分析代码，支持 pandas/numpy/matplotlib/seaborn，系统会执行并返回结果
- html: 交互式图表推荐使用 HTML + Chart.js/ECharts

### 示例

文档输出：
<!--OUTPUT_FORMAT:md-->
# 报告标题
...内容...

SVG 图表：
<!--OUTPUT_FORMAT:svg-->
<svg viewBox="0 0 400 300">...</svg>

matplotlib 图表：
<!--OUTPUT_FORMAT:png_code-->
import matplotlib.pyplot as plt
plt.plot([1,2,3], [4,5,6])
plt.title('示例图表')

图片处理（增强、滤镜、调整等）：
<!--OUTPUT_FORMAT:img_code-->
from PIL import Image, ImageEnhance, ImageFilter
# INPUT_PATH 和 OUTPUT_PATH 由系统自动注入
img = Image.open(INPUT_PATH)
enhancer = ImageEnhance.Sharpness(img)
img = enhancer.enhance(1.5)
img.save(OUTPUT_PATH)

数据分析（推荐用于数据理解任务）：
<!--OUTPUT_FORMAT:analysis_code-->
# FILE_PATHS 由系统自动注入，包含所有输入文件
df = pd.read_excel(FILE_PATHS[0])
print(df.describe())
print(df.info())
# 可以使用 save_figure() 保存图表，save_data(df) 保存数据

请根据任务性质选择最合适的输出格式，然后输出内容。不要输出额外的解释。
"""

            # 构建用户消息，包含文件内容（支持多模态）
            user_message = user_input or f"请执行「{skill.name}」任务"
            message_content = self._build_multimodal_content(user_message, file_content)

            # 调用 Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": message_content}]
            )

            ai_output = response.content[0].text
            log_ai_done()

            # 解析 AI 声明的输出格式
            output_format, clean_content = self._parse_output_format(ai_output)
            print(f"[AI Fallback] Detected output format: {output_format}")

            # 构建结果
            result = {
                "message": f"AI 执行「{skill.name}」完成",
                "skill_type": "ai_fallback",
                "content": clean_content
            }

            # 根据 AI 声明的格式生成文件
            if output_format == "html" or clean_content.strip().lower().startswith(("<!doctype", "<html")):
                result["_html"] = clean_content
            elif output_format == "png_code":
                # 执行 matplotlib 代码生成图片
                image_result = self._execute_image_code(clean_content, skill.name)
                if image_result:
                    result["_output_file"] = image_result
                    result["content"] = f"图表已生成: {image_result['name']}"
                else:
                    # 执行失败，保存为 py 文件
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["message"] = "图表代码生成完成（执行失败，已保存为 .py 文件）"
            elif output_format == "img_code":
                # 执行 PIL 图片处理代码
                image_result = self._execute_img_process_code(clean_content, skill.name, file_paths)
                if image_result:
                    result["_output_file"] = image_result
                    result["content"] = f"图片处理完成: {image_result['name']}"
                else:
                    # 执行失败，保存为 py 文件供调试
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["message"] = "图片处理代码生成完成（执行失败，已保存为 .py 文件）"
            elif output_format == "analysis_code":
                # 执行数据分析代码
                analysis_result = self._execute_analysis_code(clean_content, file_paths)
                if analysis_result['success']:
                    result["content"] = analysis_result['stdout']
                    result["message"] = f"AI 执行「{skill.name}」分析完成"
                    result["_analysis_result"] = {
                        'stdout': analysis_result['stdout'],
                        'generated_files': analysis_result['generated_files']
                    }
                    # 如果生成了文件，返回第一个作为主输出
                    if analysis_result['generated_files']:
                        result["_output_file"] = analysis_result['generated_files'][0]
                        if len(analysis_result['generated_files']) > 1:
                            result["_additional_files"] = analysis_result['generated_files'][1:]
                else:
                    # 执行失败，保存代码供调试
                    filename = generate_unique_filename(skill.name, "py")
                    filepath = OUTPUTS_DIR / filename
                    filepath.write_text(clean_content, encoding="utf-8")
                    result["_output_file"] = {
                        "path": str(filepath),
                        "type": "py",
                        "name": filename,
                        "url": f"/outputs/{filename}",
                        "size": filepath.stat().st_size
                    }
                    result["content"] = f"代码执行失败:\n{analysis_result['stderr']}\n\n代码已保存为: {filename}"
                    result["message"] = "数据分析代码执行失败（已保存代码供调试）"
            elif output_format and output_format != "txt":
                # 生成对应格式的文件
                filename = generate_unique_filename(skill.name, output_format)
                filepath = OUTPUTS_DIR / filename
                filepath.write_text(clean_content, encoding="utf-8")
                file_size = filepath.stat().st_size
                result["_output_file"] = {
                    "path": str(filepath),
                    "type": output_format,
                    "name": filename,
                    "url": f"/outputs/{filename}",
                    "size": file_size
                }

            return True, result, None, clean_content

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

    def _read_files_for_ai(self, file_paths: list, max_total_chars: int = 250000) -> str:
        """
        读取上传的文件内容，转换为 AI 可以处理的文本格式（增强版）

        Args:
            file_paths: 文件路径列表
            max_total_chars: 总字符数限制（默认250000，约80k tokens）

        增强功能:
        - Excel 多 Sheet 支持
        - 字段类型信息
        - 数值字段统计摘要
        - 大文件智能采样（头部 + 尾部 + 随机样本）
        """
        import numpy as np

        contents = []
        total_chars = 0

        # 根据文件数量动态调整每个文件的限制
        num_files = len(file_paths)
        per_file_limit = max(10000, max_total_chars // max(num_files, 1))

        for file_path in file_paths:
            # 检查是否已超过总限制
            if total_chars >= max_total_chars:
                contents.append(f"\n[已达到总字符限制，跳过剩余 {len(file_paths) - len(contents)} 个文件]")
                break
            try:
                path = Path(file_path)
                if not path.exists():
                    continue

                suffix = path.suffix.lower()

                # 计算当前文件可用的字符数
                remaining_chars = max_total_chars - total_chars
                file_limit = min(per_file_limit, remaining_chars)

                file_content = ""

                # Excel 文件 - 增强版：多 Sheet 支持 + 统计信息
                if suffix in ['.xlsx', '.xls']:
                    try:
                        file_content = self._read_excel_enhanced(file_path, path.name, file_limit)
                    except Exception as e:
                        file_content = f"### {path.name}\n[Excel 读取失败: {str(e)}]"

                # CSV 文件 - 增强版：统计信息 + 智能采样
                elif suffix == '.csv':
                    try:
                        file_content = self._read_csv_enhanced(file_path, path.name, file_limit)
                    except Exception as e:
                        file_content = f"### {path.name}\n[CSV 读取失败: {str(e)}]"

                # JSON 文件
                elif suffix == '.json':
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        # 如果是数组，尝试用 DataFrame 处理
                        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                            df = pd.DataFrame(data)
                            file_content = self._format_dataframe_enhanced(df, path.name, "json_array", file_limit)
                        else:
                            json_str = json.dumps(data, ensure_ascii=False, indent=2)
                            if len(json_str) > file_limit:
                                json_str = json_str[:file_limit] + "\n...[truncated]..."
                            file_content = f"### {path.name}\n```json\n{json_str}\n```"
                    except Exception as e:
                        file_content = f"### {path.name}\n[JSON 读取失败: {str(e)}]"

                # 文本文件
                elif suffix in ['.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.vue', '.jsx', '.tsx', '.xml', '.yaml', '.yml', '.log']:
                    try:
                        text = path.read_text(encoding='utf-8')
                        if len(text) > file_limit:
                            text = text[:file_limit] + "\n...[truncated]..."
                        lang = suffix.lstrip('.') if suffix not in ['.txt', '.log'] else ''
                        file_content = f"### {path.name}\n```{lang}\n{text}\n```"
                    except Exception:
                        pass

                # 图片文件 - 转为 base64 供 AI 分析
                elif suffix in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                    try:
                        import base64
                        img_data = path.read_bytes()
                        img_base64 = base64.b64encode(img_data).decode('utf-8')
                        # 限制图片大小（base64 会增大约 33%）
                        if len(img_base64) > 500000:  # ~375KB 原图
                            file_content = f"### {path.name}\n[图片文件过大，已跳过。文件大小: {len(img_data)} bytes]"
                        else:
                            mime_type = {
                                '.png': 'image/png',
                                '.jpg': 'image/jpeg',
                                '.jpeg': 'image/jpeg',
                                '.gif': 'image/gif',
                                '.bmp': 'image/bmp',
                                '.webp': 'image/webp'
                            }.get(suffix, 'image/png')
                            # 存储图片信息供后续 API 调用使用
                            file_content = f"### {path.name}\n[IMAGE:{mime_type}:{img_base64}]"
                    except Exception as e:
                        file_content = f"### {path.name}\n[图片读取失败: {str(e)}]"

                # SVG 文件 - 作为文本处理
                elif suffix == '.svg':
                    try:
                        text = path.read_text(encoding='utf-8')
                        if len(text) > file_limit:
                            text = text[:file_limit] + "\n...[truncated]..."
                        file_content = f"### {path.name}\n```svg\n{text}\n```"
                    except Exception:
                        pass

                # PDF 文件 - 尝试提取文本
                elif suffix == '.pdf':
                    try:
                        import fitz  # PyMuPDF
                        doc = fitz.open(file_path)
                        text_parts = []
                        for page_num in range(min(10, len(doc))):  # 最多读取前10页
                            page = doc[page_num]
                            text_parts.append(f"--- Page {page_num + 1} ---\n{page.get_text()}")
                        doc.close()
                        text = "\n".join(text_parts)
                        if len(text) > file_limit:
                            text = text[:file_limit] + "\n...[truncated]..."
                        file_content = f"### {path.name}\n```\n{text}\n```"
                    except ImportError:
                        file_content = f"### {path.name}\n[PDF 文件，需要安装 PyMuPDF 库才能读取]"
                    except Exception as e:
                        file_content = f"### {path.name}\n[PDF 读取失败: {str(e)}]"

                else:
                    file_content = f"### {path.name}\n[二进制文件，类型: {suffix}]"

                # 添加内容并更新计数
                if file_content:
                    contents.append(file_content)
                    total_chars += len(file_content)

            except Exception:
                pass

        # 添加截断提示
        result = "\n\n".join(contents)
        if total_chars >= max_total_chars * 0.9:  # 接近限制时提示
            result += f"\n\n[注意：文件内容已截断以避免超过处理限制。总计 {total_chars} 字符，{len(file_paths)} 个文件]"

        return result

    def _read_excel_enhanced(self, file_path: str, file_name: str, char_limit: int) -> str:
        """
        增强版 Excel 读取：多 Sheet 支持 + 字段类型 + 统计信息
        """
        import numpy as np

        result_parts = []
        total_chars = 0

        # 读取所有 Sheet
        excel_file = pd.ExcelFile(file_path)
        sheet_names = excel_file.sheet_names

        for sheet_name in sheet_names:
            if total_chars >= char_limit:
                result_parts.append(f"\n[已达到字符限制，跳过剩余 Sheet]")
                break

            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                remaining = char_limit - total_chars
                sheet_content = self._format_dataframe_enhanced(
                    df, f"{file_name} - Sheet: {sheet_name}", "excel", remaining
                )
                result_parts.append(sheet_content)
                total_chars += len(sheet_content)
            except Exception as e:
                result_parts.append(f"### {file_name} - Sheet: {sheet_name}\n[读取失败: {str(e)}]")

        return "\n\n".join(result_parts)

    def _read_csv_enhanced(self, file_path: str, file_name: str, char_limit: int) -> str:
        """
        增强版 CSV 读取：字段类型 + 统计信息 + 智能采样
        """
        df = pd.read_csv(file_path)
        return self._format_dataframe_enhanced(df, file_name, "csv", char_limit)

    def _format_dataframe_enhanced(self, df: pd.DataFrame, file_name: str, format_type: str, char_limit: int) -> str:
        """
        格式化 DataFrame 为增强版文本输出

        包含：
        - 基本信息（行数 x 列数）
        - 字段类型信息
        - 数值字段统计摘要
        - 数据预览（智能采样）
        """
        import numpy as np

        parts = []
        total_rows, total_cols = df.shape

        # 1. 标题和基本信息
        parts.append(f"### {file_name} ({total_rows}行 x {total_cols}列)")

        # 2. 字段类型信息
        dtype_info = ", ".join([f"{col}:{df[col].dtype}" for col in df.columns[:15]])
        if len(df.columns) > 15:
            dtype_info += f"... (+{len(df.columns) - 15} 列)"
        parts.append(f"\n**字段类型:** {dtype_info}")

        # 3. 统计摘要表格
        summary_lines = ["| 字段 | 类型 | 非空 | 唯一值 | 示例/统计 |", "|------|------|------|--------|-----------|"]

        for col in df.columns[:20]:  # 最多显示20个字段
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            unique_count = df[col].nunique()

            # 根据类型生成不同的示例/统计信息
            if pd.api.types.is_numeric_dtype(df[col]):
                # 数值类型：显示 min/max/mean
                try:
                    col_min = df[col].min()
                    col_max = df[col].max()
                    col_mean = df[col].mean()
                    if pd.api.types.is_integer_dtype(df[col]):
                        example = f"min={col_min}, max={col_max}, mean={col_mean:.1f}"
                    else:
                        example = f"min={col_min:.2f}, max={col_max:.2f}, mean={col_mean:.2f}"
                except Exception:
                    example = str(df[col].dropna().head(3).tolist())[:30]
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                # 日期类型：显示范围
                try:
                    date_min = df[col].min()
                    date_max = df[col].max()
                    example = f"{date_min} ~ {date_max}"
                except Exception:
                    example = str(df[col].dropna().head(2).tolist())[:30]
            else:
                # 其他类型：显示前几个示例值
                sample_vals = df[col].dropna().head(3).tolist()
                example = ", ".join([str(v)[:15] for v in sample_vals])
                if len(example) > 35:
                    example = example[:35] + "..."

            summary_lines.append(f"| {col[:20]} | {dtype} | {non_null} | {unique_count} | {example} |")

        if len(df.columns) > 20:
            summary_lines.append(f"| ... | ... | ... | ... | (+{len(df.columns) - 20} 列) |")

        parts.append("\n**统计摘要:**")
        parts.append("\n".join(summary_lines))

        # 4. 数据预览 - 智能采样
        max_preview_rows = min(500, max(100, char_limit // 300))  # 根据字符限制调整

        if total_rows <= max_preview_rows:
            # 数据量小，全部显示
            preview_df = df
            preview_note = ""
        else:
            # 智能采样：头部 + 尾部 + 随机样本
            head_rows = min(100, max_preview_rows // 3)
            tail_rows = min(50, max_preview_rows // 6)
            random_rows = max_preview_rows - head_rows - tail_rows

            head_df = df.head(head_rows)
            tail_df = df.tail(tail_rows)

            # 随机采样中间部分
            middle_indices = range(head_rows, total_rows - tail_rows)
            if len(middle_indices) > random_rows and random_rows > 0:
                sample_indices = sorted(np.random.choice(list(middle_indices), random_rows, replace=False))
                middle_df = df.iloc[sample_indices]
            else:
                middle_df = pd.DataFrame()

            # 合并预览数据
            preview_parts = [head_df]
            if not middle_df.empty:
                preview_parts.append(middle_df)
            preview_parts.append(tail_df)
            preview_df = pd.concat(preview_parts, ignore_index=False)

            preview_note = f" (智能采样: 前{head_rows}行 + 随机{len(middle_df)}行 + 后{tail_rows}行)"

        parts.append(f"\n**数据预览{preview_note}:**")
        parts.append(f"```\n{preview_df.to_string(max_rows=max_preview_rows)}\n```")

        result = "\n".join(parts)

        # 如果结果超过限制，截断
        if len(result) > char_limit:
            result = result[:char_limit] + "\n...[truncated]..."

        return result

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
