import uuid
import shutil
import zipfile
import json
import anthropic
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from config import get_settings
from schemas.skill import SkillCreate, SkillUpdate, SkillResponse, SkillVersionResponse
from models.skill import Skill

settings = get_settings()

router = APIRouter(prefix="/api/skills", tags=["Skills"])

# 技能文件夹存储目录
SKILLS_STORAGE_DIR = Path(__file__).parent.parent / "skills_storage"
SKILLS_STORAGE_DIR.mkdir(exist_ok=True)

# 临时技能文件夹（用于测试）
TEMP_SKILLS_STORAGE_DIR = Path(__file__).parent.parent / "skills_storage_temp"
TEMP_SKILLS_STORAGE_DIR.mkdir(exist_ok=True)


@router.get("", response_model=List[SkillResponse])
async def get_skills(db: Session = Depends(get_db)):
    """获取所有当前版本的技能（status=active）"""
    skills = db.query(Skill).filter(
        Skill.status == "active"
    ).order_by(Skill.original_created_at.asc()).all()
    return skills


@router.get("/by-name/{name}", response_model=SkillResponse)
async def get_skill_by_name(name: str, db: Session = Depends(get_db)):
    """根据名称获取技能"""
    skill = db.query(Skill).filter(Skill.name == name).first()
    if not skill:
        raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
    return skill


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: Session = Depends(get_db)):
    """获取单个技能"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(skill_data: SkillCreate, db: Session = Depends(get_db)):
    """
    手动创建技能

    如果提供了 code 字段，会自动创建文件夹和脚本文件
    如果没有提供 code，会创建一个 AI 型技能（SKILL.md）
    """
    skill_id = str(uuid.uuid4())
    skill_folder = SKILLS_STORAGE_DIR / skill_id
    skill_folder.mkdir(parents=True, exist_ok=True)

    entry_script = skill_data.entry_script or "main.py"

    # 如果提供了代码，创建 Python 脚本
    if skill_data.code:
        script_path = skill_folder / entry_script
        script_path.write_text(skill_data.code, encoding="utf-8")
    else:
        # 没有提供代码，创建 AI 型技能（SKILL.md）
        skill_md_content = f"""# {skill_data.name}

## 技能说明
{skill_data.description or '这是一个 AI 驱动的技能。'}

## 功能
根据用户输入的需求，使用 AI 智能处理并生成结果。

## 使用方式
直接描述你的需求，AI 会根据技能的定位来处理你的请求。

## 标签
{', '.join(skill_data.tags) if skill_data.tags else '通用'}

---
*此技能由 AI Skills Platform 自动创建*
"""
        skill_md_path = skill_folder / "SKILL.md"
        skill_md_path.write_text(skill_md_content, encoding="utf-8")
        entry_script = None  # AI 型技能没有入口脚本

    # 处理 output_config
    output_config_dict = None
    if skill_data.output_config:
        output_config_dict = skill_data.output_config.model_dump()

    # 写入 config.json
    config = {
        "name": skill_data.name,
        "description": skill_data.description,
        "icon": skill_data.icon,
        "tags": skill_data.tags or [],
        "author": skill_data.author,
        "version": skill_data.version or "1.0.0",
        "entry_script": entry_script,
        "type": "python" if skill_data.code else "ai_prompt",
        "output_config": output_config_dict  # 输出配置
    }
    config_path = skill_folder / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 新建技能，group_id = id（首个版本）
    skill = Skill(
        id=skill_id,
        group_id=skill_id,  # 首个版本，group_id 等于 id
        name=skill_data.name,
        description=skill_data.description,
        icon=skill_data.icon,
        tags=skill_data.tags,
        folder_path=skill_id,  # 始终设置 folder_path
        entry_script=entry_script,
        author=skill_data.author,
        version=skill_data.version or "1.0.0",
        status="active",
        interactions=([i.model_dump() for i in skill_data.interactions]
                     if skill_data.interactions else []),
        output_config=output_config_dict  # 输出配置
        # original_created_at 会自动设置为当前时间
    )

    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.post("/upload/preview")
async def preview_upload(file: UploadFile = File(..., description="技能文件夹的 ZIP 压缩包")):
    """
    预览 ZIP 包内容，使用 AI 分析代码生成准确描述

    返回从 ZIP 包中解析出的技能信息 + AI 分析结果
    """
    import io

    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传 ZIP 压缩包")

    try:
        content = await file.read()

        # 从 ZIP 中读取文件
        config_data = {}
        entry_script = None
        files_list = []
        code_contents = {}  # 用于 AI 分析的代码内容

        with zipfile.ZipFile(io.BytesIO(content), 'r') as zip_ref:
            namelist = zip_ref.namelist()

            # 检查是否有嵌套文件夹
            prefix = ""
            if namelist:
                first_item = namelist[0]
                if '/' in first_item:
                    potential_prefix = first_item.split('/')[0] + '/'
                    if all(n.startswith(potential_prefix) or n == potential_prefix.rstrip('/') for n in namelist):
                        prefix = potential_prefix

            # 查找 config.json
            config_path = prefix + "config.json"
            if config_path in namelist:
                try:
                    config_content = zip_ref.read(config_path).decode('utf-8')
                    config_data = json.loads(config_content)
                except Exception:
                    pass

            # 列出文件并读取关键文件内容
            key_files = ['main.py', 'run.py', 'index.py', 'skill.py', 'README.md', 'readme.md', 'SKILL.md']
            for name in namelist:
                if name.endswith('/'):
                    continue
                relative_name = name[len(prefix):] if prefix else name
                if relative_name:
                    files_list.append(relative_name)
                    # 自动检测入口脚本
                    if not entry_script and relative_name in ['main.py', 'run.py', 'index.py', 'skill.py']:
                        entry_script = relative_name
                    # 读取关键文件用于 AI 分析
                    if relative_name in key_files:
                        try:
                            file_content = zip_ref.read(name).decode('utf-8')
                            # 限制长度避免 token 过多
                            if len(file_content) > 3000:
                                file_content = file_content[:3000] + "\n... (truncated)"
                            code_contents[relative_name] = file_content
                        except Exception:
                            pass

        # 从文件名提取默认名称
        default_name = file.filename.replace('.zip', '').replace('.ZIP', '')

        # 基础信息
        result = {
            "name": config_data.get("name", default_name),
            "description": config_data.get("description", ""),
            "icon": config_data.get("icon", "⚡"),
            "tags": config_data.get("tags", []),
            "author": config_data.get("author", ""),
            "version": config_data.get("version", "1.0.0"),
            "entry_script": config_data.get("entry_script", entry_script),
            "files": files_list,
            "ai_analysis": None  # AI 分析结果
        }

        # 如果有代码内容，使用 AI 分析
        if code_contents:
            try:
                ai_analysis = await _analyze_skill_with_ai(code_contents, config_data)
                result["ai_analysis"] = ai_analysis
                # 如果原描述为空，使用 AI 生成的描述
                if not result["description"] and ai_analysis.get("description"):
                    result["description"] = ai_analysis["description"]
                # 如果没有标签，使用 AI 推荐的标签
                if not result["tags"] and ai_analysis.get("tags"):
                    result["tags"] = ai_analysis["tags"]
                # 如果图标是默认的，使用 AI 推荐的
                if result["icon"] == "⚡" and ai_analysis.get("icon"):
                    result["icon"] = ai_analysis["icon"]
            except Exception as e:
                print(f"AI analysis failed: {e}")
                result["ai_analysis"] = {"error": str(e)}

        return result

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


async def _analyze_skill_with_ai(code_contents: dict, config_data: dict) -> dict:
    """使用 AI 分析技能代码，提取功能描述"""

    # 构建分析内容
    content_parts = []
    for filename, content in code_contents.items():
        content_parts.append(f"=== {filename} ===\n{content}")

    code_text = "\n\n".join(content_parts)

    if config_data:
        code_text += f"\n\n=== config.json ===\n{json.dumps(config_data, ensure_ascii=False, indent=2)}"

    prompt = f"""分析以下技能代码，提取关键信息。请用中文回答。

{code_text}

请分析并返回 JSON 格式（不要包含 markdown 代码块）：
{{
    "description": "一句话描述这个技能能做什么（不超过50字）",
    "capabilities": ["能力1", "能力2", "能力3"],
    "input_types": ["支持的输入类型，如：Excel文件、文本、图片等"],
    "output_types": ["输出类型，如：报表、图表、文档等"],
    "tags": ["推荐的标签，2-4个"],
    "icon": "推荐的图标emoji",
    "complexity": "简单/中等/复杂"
}}"""

    try:
        client_kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        client = anthropic.Anthropic(**client_kwargs)

        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()
        # 尝试解析 JSON - 可能被 markdown 代码块包裹
        json_text = result_text
        if '```json' in result_text:
            json_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            json_text = result_text.split('```')[1].split('```')[0].strip()

        return json.loads(json_text)
    except json.JSONDecodeError:
        # 如果解析失败，返回空分析结果，不影响正常使用
        return {"description": None}
    except Exception as e:
        # AI 分析失败不应该阻止上传
        print(f"AI analysis error: {e}")
        return {"description": None}


@router.post("/upload", response_model=SkillResponse, status_code=201)
async def upload_skill(
    file: UploadFile = File(..., description="技能文件夹的 ZIP 压缩包"),
    name: str = Form(..., description="技能名称"),
    description: Optional[str] = Form(None, description="技能描述"),
    icon: Optional[str] = Form("⚡", description="图标"),
    tags: Optional[str] = Form(None, description="标签，JSON 数组格式"),
    entry_script: Optional[str] = Form("main.py", description="入口脚本"),
    author: Optional[str] = Form(None, description="作者"),
    version: Optional[str] = Form("1.0.0", description="版本"),
    db: Session = Depends(get_db)
):
    """
    上传技能文件夹（ZIP 压缩包）

    文件夹结构示例：
    ```
    my-skill/
    ├── main.py          # 入口脚本
    ├── requirements.txt # 依赖（可选）
    └── config.json      # 配置（可选）
    ```
    """
    # 验证文件类型
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传 ZIP 压缩包")

    # 生成 UUID
    skill_id = str(uuid.uuid4())
    skill_folder = SKILLS_STORAGE_DIR / skill_id

    try:
        # 保存并解压 ZIP 文件
        temp_zip = SKILLS_STORAGE_DIR / f"temp_{skill_id}.zip"
        content = await file.read()
        temp_zip.write_bytes(content)

        # 解压到技能文件夹
        skill_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(skill_folder)

        # 删除临时 ZIP
        temp_zip.unlink()

        # 检查是否有嵌套文件夹（常见的 ZIP 打包方式）
        items = list(skill_folder.iterdir())
        if len(items) == 1 and items[0].is_dir():
            # 将内容移动到上层
            nested_folder = items[0]
            for item in nested_folder.iterdir():
                shutil.move(str(item), str(skill_folder / item.name))
            nested_folder.rmdir()

        # 解析标签
        tags_list = []
        if tags:
            try:
                tags_list = json.loads(tags)
            except json.JSONDecodeError:
                tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        # 尝试从 config.json 读取额外信息（但不覆盖 author，保持上传标记）
        config_file = skill_folder / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                if not description and "description" in config:
                    description = config["description"]
                if not tags_list and "tags" in config:
                    tags_list = config["tags"]
                if "icon" in config:
                    icon = config["icon"]
                # 注意：不从 config.json 读取 author，保持上传的 skill 标记为 'uploaded'
                if "version" in config:
                    version = config["version"]
                if "entry_script" in config:
                    entry_script = config["entry_script"]
            except Exception:
                pass

        # 创建数据库记录 - 上传的 skill 强制 author='uploaded'
        skill = Skill(
            id=skill_id,
            group_id=skill_id,  # 首个版本，group_id 等于 id
            name=name,
            description=description,
            icon=icon,
            tags=tags_list,
            folder_path=skill_id,  # 相对路径就是 ID
            entry_script=entry_script,
            author='uploaded',  # 强制标记为上传，确保不可编辑
            version=version,
            status="active"
            # original_created_at 会自动设置为当前时间
        )

        db.add(skill)
        db.commit()
        db.refresh(skill)

        return skill

    except Exception as e:
        # 清理失败的上传
        if skill_folder.exists():
            shutil.rmtree(skill_folder)
        if temp_zip.exists():
            temp_zip.unlink()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    skill_data: SkillUpdate,
    db: Session = Depends(get_db)
):
    """
    更新技能 - 创建新版本

    修改会创建新版本记录和新文件夹，老版本标记为 deprecated。
    新版本继承 group_id 和 original_created_at，保持排序位置不变。
    """
    old_skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not old_skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    update_data = skill_data.model_dump(exclude_unset=True)

    # 生成新版本 ID 和文件夹
    new_skill_id = str(uuid.uuid4())
    new_skill_folder = SKILLS_STORAGE_DIR / new_skill_id
    new_skill_folder.mkdir(parents=True, exist_ok=True)

    # 复制老文件夹内容到新文件夹（如果存在）
    if old_skill.folder_path:
        old_folder = SKILLS_STORAGE_DIR / old_skill.folder_path
        if old_folder.exists():
            for item in old_folder.iterdir():
                if item.is_file():
                    shutil.copy2(str(item), str(new_skill_folder / item.name))
                elif item.is_dir():
                    shutil.copytree(str(item), str(new_skill_folder / item.name))

    # 处理代码更新
    code = update_data.pop("code", None)
    if code is not None:
        script_name = update_data.get("entry_script") or old_skill.entry_script or "main.py"
        script_path = new_skill_folder / script_name
        script_path.write_text(code, encoding="utf-8")

    # 处理 interactions
    interactions_data = old_skill.interactions or []
    if "interactions" in update_data and update_data["interactions"] is not None:
        interactions_data = [
            i.model_dump() if hasattr(i, 'model_dump') else i
            for i in update_data["interactions"]
        ]
        del update_data["interactions"]

    # 处理 output_config
    output_config_data = old_skill.output_config
    if "output_config" in update_data and update_data["output_config"] is not None:
        output_cfg = update_data["output_config"]
        output_config_data = output_cfg.model_dump() if hasattr(output_cfg, 'model_dump') else output_cfg
        del update_data["output_config"]

    # 计算新版本号
    old_version = old_skill.version or "1.0.0"
    try:
        parts = old_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        new_version = ".".join(parts)
    except:
        new_version = old_version + ".1"

    # 写入 config.json
    config = {
        "name": update_data.get("name") or old_skill.name,
        "description": update_data.get("description") or old_skill.description,
        "icon": update_data.get("icon") or old_skill.icon,
        "tags": update_data.get("tags") or old_skill.tags or [],
        "author": update_data.get("author") or old_skill.author,
        "version": update_data.get("version") or new_version,
        "entry_script": update_data.get("entry_script") or old_skill.entry_script,
        "output_config": output_config_data
    }
    config_path = new_skill_folder / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 创建新版本记录
    new_skill = Skill(
        id=new_skill_id,
        group_id=old_skill.group_id,  # 继承版本组ID
        name=update_data.get("name") or old_skill.name,
        description=update_data.get("description") or old_skill.description,
        icon=update_data.get("icon") or old_skill.icon,
        tags=update_data.get("tags") or old_skill.tags,
        folder_path=new_skill_id,
        entry_script=update_data.get("entry_script") or old_skill.entry_script,
        author=update_data.get("author") or old_skill.author,
        version=update_data.get("version") or new_version,
        status="active",
        interactions=interactions_data,
        output_config=output_config_data,
        original_created_at=old_skill.original_created_at  # 继承原始创建时间
    )

    # 老版本标记为 deprecated
    old_skill.status = "deprecated"

    db.add(new_skill)
    db.commit()
    db.refresh(new_skill)
    return new_skill


@router.put("/{skill_id}/folder", response_model=SkillResponse)
async def update_skill_folder(
    skill_id: str,
    file: UploadFile = File(..., description="新的技能文件夹 ZIP 压缩包"),
    db: Session = Depends(get_db)
):
    """更新技能文件夹"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传 ZIP 压缩包")

    skill_folder = SKILLS_STORAGE_DIR / skill_id

    try:
        # 删除旧文件夹内容
        if skill_folder.exists():
            shutil.rmtree(skill_folder)

        # 保存并解压新 ZIP
        temp_zip = SKILLS_STORAGE_DIR / f"temp_{skill_id}.zip"
        content = await file.read()
        temp_zip.write_bytes(content)

        skill_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(skill_folder)

        temp_zip.unlink()

        # 处理嵌套文件夹
        items = list(skill_folder.iterdir())
        if len(items) == 1 and items[0].is_dir():
            nested_folder = items[0]
            for item in nested_folder.iterdir():
                shutil.move(str(item), str(skill_folder / item.name))
            nested_folder.rmdir()

        # 更新 folder_path
        skill.folder_path = skill_id
        db.commit()
        db.refresh(skill)

        return skill

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, db: Session = Depends(get_db)):
    """删除技能（删除所有版本的数据库记录和文件夹）"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    # 获取同一版本组的所有技能
    all_versions = db.query(Skill).filter(Skill.group_id == skill.group_id).all()

    # 删除所有版本的文件夹
    for version in all_versions:
        if version.folder_path:
            skill_folder = SKILLS_STORAGE_DIR / version.folder_path
            if skill_folder.exists():
                shutil.rmtree(skill_folder)
        # 删除数据库记录
        db.delete(version)

    db.commit()
    return None


@router.get("/{skill_id}/files")
async def get_skill_files(skill_id: str, db: Session = Depends(get_db)):
    """获取技能文件夹中的文件列表"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not skill.folder_path:
        return {"files": []}

    skill_folder = SKILLS_STORAGE_DIR / skill.folder_path
    if not skill_folder.exists():
        return {"files": []}

    files = []
    for item in skill_folder.rglob("*"):
        if item.is_file():
            rel_path = item.relative_to(skill_folder)
            files.append({
                "name": item.name,
                "path": str(rel_path),
                "size": item.stat().st_size
            })

    return {"files": files}


@router.get("/{skill_id}/file/{file_path:path}")
async def get_skill_file_content(
    skill_id: str,
    file_path: str,
    db: Session = Depends(get_db)
):
    """获取技能文件内容"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not skill.folder_path:
        raise HTTPException(status_code=404, detail="技能没有文件夹")

    file_full_path = SKILLS_STORAGE_DIR / skill.folder_path / file_path
    if not file_full_path.exists() or not file_full_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 安全检查：防止路径遍历
    try:
        file_full_path.resolve().relative_to((SKILLS_STORAGE_DIR / skill.folder_path).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")

    try:
        content = file_full_path.read_text(encoding="utf-8")
        return {"content": content}
    except UnicodeDecodeError:
        return {"content": None, "binary": True, "size": file_full_path.stat().st_size}


# ============ 临时技能（测试用）============

@router.post("/temp", status_code=201)
async def create_temp_skill(skill_data: SkillCreate):
    """
    创建临时技能（仅用于测试，不写入数据库）

    返回临时技能 ID，可用于执行测试
    测试完成后调用 /temp/{temp_id}/finalize 正式创建
    或调用 DELETE /temp/{temp_id} 删除
    """
    temp_id = str(uuid.uuid4())
    temp_folder = TEMP_SKILLS_STORAGE_DIR / temp_id
    temp_folder.mkdir(parents=True, exist_ok=True)

    entry_script = skill_data.entry_script or "main.py"

    # 创建技能文件
    if skill_data.code:
        script_path = temp_folder / entry_script
        script_path.write_text(skill_data.code, encoding="utf-8")
    else:
        # AI 型技能
        skill_md_content = f"""# {skill_data.name}

## 技能说明
{skill_data.description or '这是一个 AI 驱动的技能。'}

## 功能
根据用户输入的需求，使用 AI 智能处理并生成结果。

## 标签
{', '.join(skill_data.tags) if skill_data.tags else '通用'}

---
*此技能由 AI Skills Platform 自动创建*
"""
        skill_md_path = temp_folder / "SKILL.md"
        skill_md_path.write_text(skill_md_content, encoding="utf-8")
        entry_script = None

    # 处理 output_config
    output_config_dict = None
    if skill_data.output_config:
        output_config_dict = skill_data.output_config.model_dump()

    # 写入 config.json
    config = {
        "name": skill_data.name,
        "description": skill_data.description,
        "icon": skill_data.icon,
        "tags": skill_data.tags or [],
        "author": skill_data.author,
        "version": skill_data.version or "1.0.0",
        "entry_script": entry_script,
        "type": "python" if skill_data.code else "ai_prompt",
        "output_config": output_config_dict,
        "is_temp": True  # 标记为临时
    }
    config_path = temp_folder / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "temp_id": temp_id,
        "name": skill_data.name,
        "description": skill_data.description,
        "icon": skill_data.icon,
        "tags": skill_data.tags,
        "folder_path": f"temp:{temp_id}",  # 标记为临时路径
        "entry_script": entry_script
    }


@router.post("/temp/{temp_id}/finalize", response_model=SkillResponse, status_code=201)
async def finalize_temp_skill(temp_id: str, db: Session = Depends(get_db)):
    """
    将临时技能正式化（移动到正式目录并写入数据库）
    """
    temp_folder = TEMP_SKILLS_STORAGE_DIR / temp_id
    if not temp_folder.exists():
        raise HTTPException(status_code=404, detail="临时技能不存在或已过期")

    # 读取 config.json
    config_path = temp_folder / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="临时技能配置缺失")

    config = json.loads(config_path.read_text(encoding="utf-8"))

    # 生成正式 ID
    skill_id = str(uuid.uuid4())
    skill_folder = SKILLS_STORAGE_DIR / skill_id

    # 移动文件夹
    shutil.move(str(temp_folder), str(skill_folder))

    # 更新 config.json 移除 is_temp 标记
    config.pop("is_temp", None)
    config_path = skill_folder / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 处理 output_config
    output_config_dict = config.get("output_config")

    # 创建数据库记录
    skill = Skill(
        id=skill_id,
        group_id=skill_id,  # 首个版本，group_id 等于 id
        name=config.get("name", "Unnamed Skill"),
        description=config.get("description"),
        icon=config.get("icon"),
        tags=config.get("tags"),
        folder_path=skill_id,
        entry_script=config.get("entry_script"),
        author=config.get("author"),
        version=config.get("version"),
        status="active",
        output_config=output_config_dict
        # original_created_at 会自动设置为当前时间
    )

    db.add(skill)
    db.commit()
    db.refresh(skill)

    return skill


@router.delete("/temp/{temp_id}", status_code=204)
async def delete_temp_skill(temp_id: str):
    """
    删除临时技能
    """
    temp_folder = TEMP_SKILLS_STORAGE_DIR / temp_id
    if temp_folder.exists():
        shutil.rmtree(temp_folder)
    return None


@router.get("/temp/{temp_id}")
async def get_temp_skill(temp_id: str):
    """
    获取临时技能信息
    """
    temp_folder = TEMP_SKILLS_STORAGE_DIR / temp_id
    if not temp_folder.exists():
        raise HTTPException(status_code=404, detail="临时技能不存在或已过期")

    config_path = temp_folder / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="临时技能配置缺失")

    config = json.loads(config_path.read_text(encoding="utf-8"))

    return {
        "temp_id": temp_id,
        "name": config.get("name"),
        "description": config.get("description"),
        "icon": config.get("icon"),
        "tags": config.get("tags"),
        "folder_path": f"temp:{temp_id}",
        "entry_script": config.get("entry_script"),
        "is_temp": True
    }


# ============ 版本管理 ============

@router.get("/{skill_id}/versions", response_model=List[SkillVersionResponse])
async def get_skill_versions(skill_id: str, db: Session = Depends(get_db)):
    """获取技能的所有历史版本"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    # 获取同一版本组的所有版本，按创建时间降序
    versions = db.query(Skill).filter(
        Skill.group_id == skill.group_id
    ).order_by(Skill.created_at.desc()).all()

    return versions


@router.post("/{skill_id}/rollback/{target_version_id}", response_model=SkillResponse)
async def rollback_skill(
    skill_id: str,
    target_version_id: str,
    db: Session = Depends(get_db)
):
    """
    回退到指定历史版本

    会创建一个新版本（复制目标版本的内容），当前版本标记为 deprecated
    """
    current_skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not current_skill:
        raise HTTPException(status_code=404, detail="当前技能不存在")

    target_skill = db.query(Skill).filter(Skill.id == target_version_id).first()
    if not target_skill:
        raise HTTPException(status_code=404, detail="目标版本不存在")

    # 验证是同一版本组
    if current_skill.group_id != target_skill.group_id:
        raise HTTPException(status_code=400, detail="目标版本不属于同一技能")

    # 创建新版本（基于目标版本）
    new_skill_id = str(uuid.uuid4())
    new_skill_folder = SKILLS_STORAGE_DIR / new_skill_id
    new_skill_folder.mkdir(parents=True, exist_ok=True)

    # 复制目标版本的文件夹
    if target_skill.folder_path:
        target_folder = SKILLS_STORAGE_DIR / target_skill.folder_path
        if target_folder.exists():
            for item in target_folder.iterdir():
                if item.is_file():
                    shutil.copy2(str(item), str(new_skill_folder / item.name))
                elif item.is_dir():
                    shutil.copytree(str(item), str(new_skill_folder / item.name))

    # 计算新版本号
    old_version = current_skill.version or "1.0.0"
    try:
        parts = old_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        new_version = ".".join(parts)
    except:
        new_version = old_version + ".1"

    # 创建新版本记录（基于目标版本的内容）
    new_skill = Skill(
        id=new_skill_id,
        group_id=current_skill.group_id,
        name=target_skill.name,
        description=target_skill.description,
        icon=target_skill.icon,
        tags=target_skill.tags,
        folder_path=new_skill_id,
        entry_script=target_skill.entry_script,
        author=target_skill.author,
        version=new_version,
        status="active",
        interactions=target_skill.interactions,
        output_config=target_skill.output_config,
        original_created_at=current_skill.original_created_at
    )

    # 当前版本标记为 deprecated
    current_skill.status = "deprecated"

    db.add(new_skill)
    db.commit()
    db.refresh(new_skill)
    return new_skill
